import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from metrics.health import StreamHealth
from metrics.stream.classifier import FlowRunEventClassifier
from metrics.stream.client import EventStream, StreamSettings
from metrics.stream.counters import FlowRunStreamMetrics
from tests.stream_fakes import FakeEventsServer, Relay, event_message, wait_until

FIXTURES = Path(__file__).parent / "fixtures" / "events"
EVENTS = json.loads((FIXTURES / "oss_flow_run_states.json").read_text())
TERMINALS = [e for e in EVENTS if e["resource"]["prefect.state-type"] == "COMPLETED"]


class UpperJitter(random.Random):
    """Backoff jitter that always picks the longest delay."""

    def uniform(self, a, b):
        return b


class Harness:
    """An EventStream against a fake server, with its own metric registry."""

    def __init__(self, port, **overrides):
        settings = dict(
            api_url=f"http://127.0.0.1:{port}/api",
            token="secret",
            backfill_window=5.0,
            ping_interval=0.05,
            ping_timeout=0.1,
            replace_after=3600.0,
            delivering_grace=0.2,
            backoff_initial=0.01,
            backoff_max=0.05,
            refusal_retry=0.2,
            open_timeout=2.0,
        )
        stream_disabled = overrides.pop("stream_disabled", False)
        settings.update(overrides)
        self.registry = CollectorRegistry()
        self.health = StreamHealth(self.registry)
        self.metrics = FlowRunStreamMetrics(self.registry)
        self.stream = EventStream(
            StreamSettings(**settings),
            FlowRunEventClassifier(),
            self.metrics,
            self.health,
            logging.getLogger("test"),
            stream_disabled=stream_disabled,
            rng=UpperJitter(),
        )
        self.task = None

    def value(self, name, **labels):
        return self.registry.get_sample_value(name, labels) or 0.0

    def completed_count(self):
        return sum(
            s.value
            for m in self.registry.collect()
            if m.name == "prefect_flow_runs_terminal"
            for s in m.samples
            if s.name == "prefect_flow_runs_terminal_total"
            and s.labels["state_type"] == "COMPLETED"
        )

    async def __aenter__(self):
        self.task = asyncio.create_task(self.stream.run())
        return self

    async def __aexit__(self, *exc):
        self.stream._stop.set()
        await asyncio.wait_for(self.task, 5)


def run(coro):
    asyncio.run(asyncio.wait_for(coro, 20))


async def _send(ws, events):
    for event in events:
        await ws.send(event_message(event))


def _hold_after(events):
    async def script(ws, filter_message):
        await _send(ws, events)
        await ws.wait_closed()

    return script


def _close_after(events, code, reason=""):
    async def script(ws, filter_message):
        await _send(ws, events)
        await ws.close(code, reason)

    return script


def test_first_connect_refuses_backfill_and_reconnects_resume_from_the_last_event():
    async def scenario():
        async with FakeEventsServer() as server:
            last = TERMINALS[0]
            server.scripts = [_close_after([last], 1001)]
            async with Harness(server.port) as harness:
                await wait_until(lambda: len(server.filters) == 2)

            first, second = server.filters
            assert first["backfill"] is False
            assert second["backfill"] is True
            assert datetime.fromisoformat(
                second["filter"]["occurred"]["since"]
            ) == datetime.fromisoformat(last["occurred"]) - timedelta(minutes=1)
            assert first["filter"]["event"] == {
                "prefix": ["prefect.flow-run."],
                "exclude_prefix": [
                    "prefect.flow-run.heartbeat",
                    "prefect.flow-run.pull-step.",
                ],
            }
            until = datetime.fromisoformat(first["filter"]["occurred"]["until"])
            assert until - datetime.now(until.tzinfo) > timedelta(days=364)
            assert (
                harness.value(
                    "prefect_exporter_stream_reconnects_total", reason="server_close"
                )
                == 1
            )

    run(scenario())


def test_subscription_authenticates_with_the_token_on_the_prefect_subprotocol():
    async def scenario():
        async with FakeEventsServer() as server:
            async with Harness(server.port) as harness:
                await wait_until(lambda: len(server.filters) == 1)
                assert harness.value("prefect_exporter_stream_connected") == 1
            assert server.auths == [{"type": "auth", "token": "secret"}]
            assert server.subprotocols == ["prefect"]

    run(scenario())


@pytest.mark.parametrize(
    "close, reason",
    [
        ((1000, ""), "server_close"),
        ((1001, "going away"), "server_close"),
        ((1011, "boom"), "server_close"),
        ("cut", "error"),
    ],
)
def test_every_kind_of_close_is_reconnected(close, reason):
    async def scenario():
        async with FakeEventsServer() as server:
            async with Relay(server.port) as relay:
                if close == "cut":
                    server.scripts = [_hold_after([TERMINALS[0]])]
                else:
                    server.scripts = [_close_after([TERMINALS[0]], *close)]
                async with Harness(relay.port) as harness:
                    await wait_until(lambda: len(server.filters) >= 1)
                    if close == "cut":
                        await wait_until(lambda: harness.completed_count() == 1)
                        relay.cut()
                    await wait_until(lambda: len(server.filters) == 2)
                    assert (
                        harness.value(
                            "prefect_exporter_stream_reconnects_total", reason=reason
                        )
                        == 1
                    )

    run(scenario())


def test_two_immediate_retries_then_growing_delays():
    stream = Harness(1, backoff_initial=1.0, backoff_max=60.0).stream

    assert [stream._backoff(n) for n in range(1, 10)] == [
        0.0,
        0.0,
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        32.0,
        60.0,
    ]


def test_ping_timeout_closes_and_counts_from_the_last_pong():
    async def scenario():
        async with FakeEventsServer() as server:
            async with Relay(server.port) as relay:
                async with Harness(relay.port, backfill_window=0.0) as harness:
                    await wait_until(
                        lambda: harness.value("prefect_exporter_stream_connected") == 1
                    )
                    # Long enough that the last pong is well after the connect,
                    # so counting from the connect would read about 2 seconds.
                    await asyncio.sleep(2.0)
                    relay.freeze()
                    await wait_until(lambda: len(server.filters) == 2)
                    await wait_until(
                        lambda: harness.value(
                            "prefect_exporter_stream_disconnected_seconds_total"
                        )
                        > 0
                    )
                    assert (
                        harness.value(
                            "prefect_exporter_stream_reconnects_total",
                            reason="ping_timeout",
                        )
                        == 1
                    )
                    # The last pong came at most one ping interval before the
                    # freeze; the timeout fires a ping timeout later.
                    disconnected = harness.value(
                        "prefect_exporter_stream_disconnected_seconds_total"
                    )
                    assert 0.1 <= disconnected < 0.5

    run(scenario())


def test_three_failed_backfills_fall_back_to_one_connect_without_backfill():
    async def scenario():
        async with FakeEventsServer() as server:
            failing_backfill = _close_after([], 1011, "backfill query failed")
            server.scripts = [
                _close_after([TERMINALS[0]], 1001),
                failing_backfill,
                failing_backfill,
                failing_backfill,
                _close_after([TERMINALS[1]], 1001),
            ]
            async with Harness(server.port) as harness:
                await wait_until(lambda: len(server.filters) == 6)
                assert [f["backfill"] for f in server.filters] == [
                    False,
                    True,
                    True,
                    True,
                    False,
                    True,
                ]
                assert (
                    harness.value("prefect_exporter_stream_backfill_failures_total")
                    == 3
                )
                await wait_until(
                    lambda: harness.value("prefect_exporter_stream_gap_seconds_total")
                    > 0
                )
                # The fallback connect replayed nothing, so the whole first
                # disconnection is a gap.
                gap = harness.value("prefect_exporter_stream_gap_seconds_total")
                disconnected = harness.value(
                    "prefect_exporter_stream_disconnected_seconds_total"
                )
                assert gap == pytest.approx(disconnected)

    run(scenario())


@pytest.mark.parametrize(
    "backfill_window, expect_gap",
    [(5.0, False), (0.2, True)],
)
def test_gap_is_the_disconnection_backfill_did_not_cover(backfill_window, expect_gap):
    async def scenario():
        async with FakeEventsServer() as server:
            server.scripts = [_close_after([TERMINALS[0]], 1001)]
            # No immediate retries and a fixed 0.6 s delay before reconnecting.
            async with Harness(
                server.port,
                backfill_window=backfill_window,
                immediate_retries=0,
                backoff_initial=0.6,
                backoff_max=0.6,
            ) as harness:
                await wait_until(lambda: len(server.filters) == 2)
                await wait_until(
                    lambda: harness.value(
                        "prefect_exporter_stream_disconnected_seconds_total"
                    )
                    > 0
                )
                disconnected = harness.value(
                    "prefect_exporter_stream_disconnected_seconds_total"
                )
                gap = harness.value("prefect_exporter_stream_gap_seconds_total")
                assert 0.6 <= disconnected < 1.0
                if expect_gap:
                    assert gap == pytest.approx(
                        disconnected - backfill_window, abs=0.01
                    )
                else:
                    assert gap == 0

    run(scenario())


def test_replayed_terminals_after_a_reconnect_are_not_counted_twice():
    async def scenario():
        async with FakeEventsServer() as server:

            async def replay_if_asked(ws, filter_message):
                if filter_message["backfill"]:
                    await _send(ws, TERMINALS)
                await ws.wait_closed()

            server.scripts = [_close_after(TERMINALS, 1001), replay_if_asked]
            async with Harness(server.port) as harness:
                await wait_until(
                    lambda: harness.value(
                        "prefect_exporter_stream_events_total", outcome="duplicate"
                    )
                    == len(TERMINALS)
                )
                assert harness.completed_count() == len(TERMINALS)
                assert harness.value(
                    "prefect_exporter_stream_events_total", outcome="counted"
                ) == len(TERMINALS)

    run(scenario())


def test_a_restarted_process_asks_for_no_replay_and_counts_from_zero():
    async def scenario():
        async with FakeEventsServer() as server:

            async def replay_if_asked(ws, filter_message):
                if filter_message["backfill"]:
                    await _send(ws, TERMINALS)
                await ws.wait_closed()

            server.default_script = _close_after(TERMINALS, 1000)
            server.scripts = [_hold_after(TERMINALS)]
            async with Harness(server.port) as first_process:
                await wait_until(
                    lambda: first_process.completed_count() == len(TERMINALS)
                )
            server.scripts = [replay_if_asked]
            async with Harness(server.port) as restarted:
                await wait_until(lambda: len(server.filters) == 2)
                await asyncio.sleep(0.1)
                assert server.filters[1]["backfill"] is False
                assert restarted.completed_count() == 0

    run(scenario())


def test_auth_failure_is_a_refusal_retried_on_the_refusal_interval():
    async def scenario():
        async with FakeEventsServer() as server:
            server.auth_reply = {"type": "auth_failure", "reason": "missing scope"}
            async with Harness(server.port) as harness:
                await wait_until(lambda: server.connections == 1)
                await wait_until(
                    lambda: harness.value("prefect_exporter_stream_refused") == 1
                )
                await asyncio.sleep(0.1)
                assert server.connections == 1
                server.auth_reply = {"type": "auth_success"}
                server.scripts = [_hold_after([TERMINALS[0]])]
                await wait_until(lambda: len(server.filters) == 1)
                await wait_until(
                    lambda: harness.value("prefect_exporter_stream_refused") == 0
                )

    run(scenario())


def test_handshake_403_is_a_refusal():
    async def scenario():
        async with FakeEventsServer() as server:
            server.refuse_handshake_with = 403
            async with Harness(server.port) as harness:
                await wait_until(
                    lambda: harness.value("prefect_exporter_stream_refused") == 1
                )
                assert harness.value("prefect_exporter_stream_connected") == 0

    run(scenario())


def test_close_1008_after_the_filter_is_a_refusal():
    async def scenario():
        async with FakeEventsServer() as server:
            server.scripts = [_close_after([], 1008, "Run retention is disabled")]
            async with Harness(server.port) as harness:
                await wait_until(
                    lambda: harness.value("prefect_exporter_stream_refused") == 1
                )
                await asyncio.sleep(0.05)
                assert len(server.filters) == 1

    run(scenario())


def test_disabled_stream_is_reported_as_refused_while_connected():
    async def scenario():
        async with FakeEventsServer() as server:
            server.scripts = [_hold_after([])]
            async with Harness(server.port, stream_disabled=True) as harness:
                await wait_until(
                    lambda: harness.value("prefect_exporter_stream_connected") == 1
                )
                await asyncio.sleep(0.3)
                assert harness.value("prefect_exporter_stream_refused") == 1

    run(scenario())


def test_events_update_the_health_metrics():
    async def scenario():
        async with FakeEventsServer() as server:
            server.scripts = [_hold_after(EVENTS)]
            async with Harness(server.port) as harness:
                await wait_until(
                    lambda: harness.value(
                        "prefect_exporter_stream_events_total", outcome="ignored"
                    )
                    == 22
                )
                assert (
                    harness.value(
                        "prefect_exporter_stream_events_total", outcome="counted"
                    )
                    == 11
                )
                assert harness.value(
                    "prefect_exporter_stream_last_event_timestamp_seconds"
                ) == pytest.approx(datetime.now().timestamp(), abs=5)
                assert harness.value("prefect_exporter_stream_connected") == 1

    run(scenario())


def test_a_subscription_that_ends_before_delivering_still_ends_the_disconnection():
    async def scenario():
        async def short_lived(ws, filter_message):
            # Open long enough to measure, closed before the grace period.
            await asyncio.sleep(0.6)
            await ws.close(1001)

        async with FakeEventsServer() as server:
            server.scripts = [_close_after([TERMINALS[0]], 1001), short_lived]
            # Every reconnect waits a fixed 0.5 s.
            async with Harness(
                server.port,
                delivering_grace=1.0,
                immediate_retries=0,
                backoff_initial=0.5,
                backoff_max=0.5,
            ) as harness:
                await wait_until(lambda: len(server.filters) == 3)
                # The third subscription delivers after its 1 s grace period.
                await asyncio.sleep(1.3)
                # Two 0.5 s waits are disconnected time; the 0.6 s the second
                # subscription was open is not.
                assert harness.value(
                    "prefect_exporter_stream_disconnected_seconds_total"
                ) == pytest.approx(1.0, abs=0.25)

    run(scenario())


def test_a_delivering_backfill_connect_resets_the_failures_in_a_row():
    async def scenario():
        async with FakeEventsServer() as server:
            failing_backfill = _close_after([], 1011, "backfill query failed")
            server.scripts = [
                _close_after([TERMINALS[0]], 1001),
                failing_backfill,
                failing_backfill,
                _close_after([TERMINALS[1]], 1001),
                failing_backfill,
                failing_backfill,
            ]
            async with Harness(server.port):
                await wait_until(lambda: len(server.filters) == 7)
                # Two failures, a success, two failures: never three in a row,
                # so every reconnect asks for backfill.
                assert [f["backfill"] for f in server.filters] == [
                    False,
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                ]

    run(scenario())


@pytest.mark.parametrize("code", [1008, 1011])
def test_a_quiet_delivering_socket_closed_later_is_an_ordinary_close(code):
    async def scenario():
        async def quiet_then_close(ws, filter_message):
            await asyncio.sleep(0.5)
            await ws.close(code, "late close")

        async with FakeEventsServer() as server:
            server.scripts = [_close_after([TERMINALS[0]], 1001), quiet_then_close]
            async with Harness(server.port) as harness:
                await wait_until(lambda: len(server.filters) == 3)
                assert harness.value("prefect_exporter_stream_refused") == 0
                assert (
                    harness.value("prefect_exporter_stream_backfill_failures_total")
                    == 0
                )
                assert (
                    harness.value(
                        "prefect_exporter_stream_reconnects_total",
                        reason="server_close",
                    )
                    == 2
                )
                assert server.filters[2]["backfill"] is True

    run(scenario())


def test_a_malformed_frame_is_skipped_and_the_subscription_continues():
    async def scenario():
        async def bad_then_good(ws, filter_message):
            await ws.send("not json")
            await ws.send(json.dumps(["not", "a", "message"]))
            await ws.send(event_message(TERMINALS[0]))
            await ws.wait_closed()

        async with FakeEventsServer() as server:
            server.scripts = [bad_then_good]
            async with Harness(server.port) as harness:
                await wait_until(lambda: harness.completed_count() == 1)
                assert (
                    harness.value(
                        "prefect_exporter_stream_events_total", outcome="malformed"
                    )
                    == 2
                )
                assert server.connections == 1

    run(scenario())


def test_an_event_that_cannot_be_handled_does_not_move_the_cursor():
    async def scenario():
        good = TERMINALS[0]
        bad = {"occurred": "2026-11-17T18:00:00+00:00", "resource": "not a mapping"}

        async with FakeEventsServer() as server:
            server.scripts = [_close_after([good, bad], 1001)]
            async with Harness(server.port) as harness:
                await wait_until(lambda: len(server.filters) == 2)
                assert (
                    harness.value(
                        "prefect_exporter_stream_events_total", outcome="malformed"
                    )
                    == 1
                )
                assert datetime.fromisoformat(
                    server.filters[1]["filter"]["occurred"]["since"]
                ) == datetime.fromisoformat(good["occurred"]) - timedelta(minutes=1)

    run(scenario())


def test_a_future_occurred_does_not_move_the_cursor_past_now():
    async def scenario():
        future = dict(TERMINALS[0])
        future["occurred"] = (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat()

        async with FakeEventsServer() as server:
            server.scripts = [_close_after([future], 1001)]
            async with Harness(server.port):
                await wait_until(lambda: len(server.filters) == 2)
                since = datetime.fromisoformat(
                    server.filters[1]["filter"]["occurred"]["since"]
                )
                assert since <= datetime.now(timezone.utc) - timedelta(seconds=59)

    run(scenario())


def test_a_non_json_auth_reply_is_retried_and_the_stream_recovers():
    async def scenario():
        async with FakeEventsServer() as server:
            server.auth_reply = "<html>proxy error</html>"
            async with Harness(server.port) as harness:
                await wait_until(lambda: server.connections >= 2)
                assert harness.task.done() is False
                server.auth_reply = {"type": "auth_success"}
                server.scripts = [_hold_after([TERMINALS[0]])]
                await wait_until(lambda: harness.completed_count() == 1)
                assert (
                    harness.value(
                        "prefect_exporter_stream_reconnects_total", reason="error"
                    )
                    >= 2
                )

    run(scenario())


def test_an_unexpected_error_in_the_loop_is_logged_and_the_stream_continues(caplog):
    async def scenario():
        async with FakeEventsServer() as server:
            server.scripts = [_hold_after([TERMINALS[0]])]
            harness = Harness(server.port)
            original = harness.stream._subscribe
            calls = []

            async def flaky_subscribe(backfill):
                calls.append(backfill)
                if len(calls) == 1:
                    raise RuntimeError("unexpected")
                return await original(backfill)

            harness.stream._subscribe = flaky_subscribe
            async with harness:
                await wait_until(lambda: harness.completed_count() == 1)
            assert calls[1] is False
            assert "Event stream failed; reconnecting" in caplog.text

    run(scenario())


def test_a_404_handshake_is_logged_as_endpoint_not_found(caplog):
    async def scenario():
        async with FakeEventsServer() as server:
            server.refuse_handshake_with = 404
            async with Harness(server.port) as harness:
                await wait_until(
                    lambda: harness.value("prefect_exporter_stream_refused") == 1
                )
        assert "was not found (wrong URL or old server)" in caplog.text
        assert "see_events" not in caplog.text

    run(scenario())


def test_a_failed_step_closes_a_subscription_it_just_opened():
    async def scenario():
        async with FakeEventsServer() as server:
            harness = Harness(server.port)
            original = harness.stream._wait_for_end_or_replacement
            calls = []

            async def raise_once(subscription):
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("unexpected")
                await original(subscription)

            harness.stream._wait_for_end_or_replacement = raise_once
            async with harness:
                await wait_until(lambda: server.connections == 2)
                await wait_until(lambda: len(server.open_sockets) == 1)
                await asyncio.sleep(0.1)
                assert len(server.open_sockets) == 1
                assert len(harness.stream.open_subscriptions) == 1

    run(scenario())


def test_stop_before_run_starts_keeps_it_from_connecting():
    async def scenario():
        async with FakeEventsServer() as server:
            stream = Harness(server.port).stream
            stream.stop_threadsafe()
            await asyncio.wait_for(stream.run(), 2)
            assert server.connections == 0

    run(scenario())


def test_stop_after_the_loop_closed_does_not_raise():
    async def scenario(stream, server):
        task = asyncio.create_task(stream.run())
        await wait_until(lambda: len(server.filters) == 1)
        stream._stop.set()
        await task

    async def with_server():
        async with FakeEventsServer() as server:
            harness = Harness(server.port)
            # The stream runs on its own loop, as on the exporter's thread.
            await asyncio.to_thread(asyncio.run, scenario(harness.stream, server))
            harness.stream.stop_threadsafe()

    run(with_server())


def test_a_keepalive_error_ends_the_subscription_and_it_reconnects(caplog):
    async def scenario():
        async with FakeEventsServer() as server:
            async with Harness(server.port) as harness:
                await wait_until(lambda: len(harness.stream.open_subscriptions) == 1)
                [subscription] = harness.stream.open_subscriptions

                async def broken_ping(*args, **kwargs):
                    raise RuntimeError("ping failed")

                subscription.ws.ping = broken_ping
                await wait_until(lambda: server.connections == 2)
                assert subscription.end_kind == "error"
                assert (
                    harness.value(
                        "prefect_exporter_stream_reconnects_total", reason="error"
                    )
                    == 1
                )
        assert "Event stream keepalive failed" in caplog.text

    run(scenario())


class Escape(BaseException):
    """An exception the stream's catch-all does not catch."""


def test_an_escaping_error_still_starts_the_disconnected_time():
    async def scenario():
        async with FakeEventsServer() as server:
            harness = Harness(server.port)
            stream = harness.stream
            original = stream._wait_for_end_or_replacement

            async def escape(subscription):
                await asyncio.sleep(0.3)
                raise Escape()

            stream._wait_for_end_or_replacement = escape
            with pytest.raises(Escape):
                await stream.run()
            assert harness.value("prefect_exporter_stream_connected") == 0
            assert stream.disconnected_since is not None

            # A restarted run accounts the time without a subscription.
            stream._wait_for_end_or_replacement = original
            task = asyncio.create_task(stream.run())
            await wait_until(
                lambda: harness.value(
                    "prefect_exporter_stream_disconnected_seconds_total"
                )
                > 0
            )
            assert server.filters[1]["backfill"] is True
            stream._stop.set()
            await task

    run(scenario())
