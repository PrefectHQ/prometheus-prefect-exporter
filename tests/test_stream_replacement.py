import asyncio
import time

from tests.stream_fakes import FakeEventsServer, event_message, wait_until
from tests.test_stream_client import TERMINALS, Harness, run

REPLACEMENT = dict(replace_after=0.3, delivering_grace=0.2)


def _reconnects(harness):
    return sum(
        harness.value("prefect_exporter_stream_reconnects_total", reason=reason)
        for reason in ("server_close", "ping_timeout", "error")
    )


def test_replacement_overlaps_the_old_socket_and_counts_each_terminal_once():
    async def scenario():
        old_closed = asyncio.Event()

        async def old(ws, filter_message):
            await ws.send(event_message(TERMINALS[0]))
            await ws.wait_closed()
            old_closed.set()

        async def new(ws, filter_message):
            # The replay of the backfill window, which repeats the old
            # socket's event, then a live event.
            await ws.send(event_message(TERMINALS[0]))
            await asyncio.sleep(0.15)
            await ws.send(event_message(TERMINALS[1]))
            await ws.wait_closed()

        async with FakeEventsServer() as server:
            server.scripts = [old, new]
            async with Harness(server.port, **REPLACEMENT) as harness:
                await asyncio.wait_for(old_closed.wait(), 5)
                await wait_until(lambda: harness.completed_count() == 2)
                await asyncio.sleep(0.05)
                assert [f["backfill"] for f in server.filters][:2] == [False, True]
                assert harness.completed_count() == 2
                assert (
                    harness.value(
                        "prefect_exporter_stream_events_total", outcome="duplicate"
                    )
                    == 1
                )
                assert _reconnects(harness) == 0
                assert (
                    harness.value("prefect_exporter_stream_disconnected_seconds_total")
                    == 0
                )
                assert harness.value("prefect_exporter_stream_connected") == 1

    run(scenario())


def test_quiet_replacement_closes_the_old_socket_after_the_grace_period():
    async def scenario():
        async with FakeEventsServer() as server:
            async with Harness(server.port, **REPLACEMENT):
                await wait_until(lambda: len(server.filters) == 2)
                opened = time.monotonic()
                assert len(server.open_sockets) == 2
                await wait_until(lambda: len(server.open_sockets) == 1)
                assert time.monotonic() - opened >= 0.15

    run(scenario())


def test_failed_replacement_keeps_the_old_socket_and_tries_again():
    async def scenario():
        async def failing_backfill(ws, filter_message):
            await ws.close(1011, "backfill query failed")

        async with FakeEventsServer() as server:
            server.scripts = [server.default_script, failing_backfill]
            async with Harness(server.port, **REPLACEMENT) as harness:
                await wait_until(lambda: len(server.filters) == 3)
                assert [f["backfill"] for f in server.filters] == [False, True, True]
                assert (
                    harness.value("prefect_exporter_stream_backfill_failures_total")
                    == 1
                )
                await wait_until(lambda: len(server.open_sockets) == 1)
                assert _reconnects(harness) == 0
                assert harness.value("prefect_exporter_stream_connected") == 1

    run(scenario())


def test_old_socket_closed_by_the_server_during_the_overlap_leaves_no_gap():
    async def scenario():
        async def capped(ws, filter_message):
            # Ends the old socket while the replacement is in its grace period.
            await asyncio.sleep(0.4)
            await ws.close(1001, "load balancer timeout")

        async with FakeEventsServer() as server:
            server.scripts = [capped]
            async with Harness(server.port, **REPLACEMENT) as harness:
                await wait_until(lambda: len(server.filters) == 2)
                await asyncio.sleep(0.4)
                assert all(f["backfill"] for f in server.filters[1:])
                assert _reconnects(harness) == 0
                assert (
                    harness.value("prefect_exporter_stream_disconnected_seconds_total")
                    == 0
                )

    run(scenario())


def test_failed_replacements_back_off_and_then_fall_back_to_no_backfill():
    async def scenario():
        async def failing_backfill(ws, filter_message):
            await ws.close(1011, "backfill query failed")

        async with FakeEventsServer() as server:
            server.scripts = [
                server.default_script,
                failing_backfill,
                failing_backfill,
                failing_backfill,
            ]
            async with Harness(
                server.port,
                replace_after=0.2,
                delivering_grace=0.2,
                backoff_initial=0.1,
                backoff_max=2.0,
            ) as harness:
                await wait_until(lambda: len(server.filters) == 5)
                flags = [f["backfill"] for f in server.filters]
                times = server.filter_times
                # The fourth attempt follows three failures in a row, so it
                # asks for no backfill.
                assert flags == [False, True, True, True, False]
                # Delays between replacement attempts double: 0.1, 0.2, 0.4 s.
                intervals = [b - a for a, b in zip(times[1:4], times[2:5])]
                assert intervals[0] >= 0.09
                assert intervals[1] >= 0.18
                assert intervals[2] >= 0.36
                assert _reconnects(harness) == 0
                assert (
                    harness.value("prefect_exporter_stream_backfill_failures_total")
                    == 3
                )
                # The fallback replacement delivered, so the next one asks
                # for backfill again.
                await wait_until(lambda: len(server.filters) == 6)
                assert server.filters[5]["backfill"] is True

    run(scenario())
