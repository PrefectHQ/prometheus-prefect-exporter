import asyncio
import json
import logging
import threading
import time
from pathlib import Path

import pytest
import responses
from prometheus_client import CollectorRegistry, generate_latest

from metrics.config import Config
from metrics.exporter import Exporter
from metrics.stream.protocol import close_kind, events_out_url
from tests.stream_fakes import FakeEventsServer, event_message

FIXTURES = Path(__file__).parent / "fixtures" / "events"
EVENTS = json.loads((FIXTURES / "oss_flow_run_states.json").read_text())
CLOUD_URL = "https://api.prefect.cloud/api/accounts/a1/workspaces/w1"


@pytest.mark.parametrize(
    "env, cloud, window, token",
    [
        ({}, False, 900.0, None),
        ({"PREFECT_API_URL": CLOUD_URL, "PREFECT_API_KEY": "k"}, True, 120.0, "k"),
        (
            {
                "PREFECT_API_URL": CLOUD_URL + "/",
                "STREAM_BACKFILL_WINDOW_SECONDS": "30",
            },
            True,
            30.0,
            None,
        ),
        ({"PREFECT_API_AUTH_STRING": "admin:pass"}, False, 900.0, "admin:pass"),
        (
            {"PREFECT_API_AUTH_STRING": "admin:pass", "PREFECT_API_KEY": "k"},
            False,
            900.0,
            "k",
        ),
    ],
)
def test_config_derives_the_stream_settings_from_the_server_kind(
    env, cloud, window, token
):
    config = Config.from_env(env)

    assert config.is_cloud is cloud
    assert config.backfill_window_seconds == window
    assert config.stream_token == token


def test_config_defaults():
    config = Config.from_env({})

    assert config.inventory_poll_interval == 300
    assert config.run_poll_interval == 60
    assert config.duplicate_memory_hours == 24
    assert config.failed_runs_offset_minutes == 10080


@pytest.mark.parametrize(
    "api_url, socket_url",
    [
        ("http://localhost:4200/api", "ws://localhost:4200/api/events/out"),
        (CLOUD_URL, "wss://api.prefect.cloud/api/accounts/a1/workspaces/w1/events/out"),
    ],
)
def test_events_out_url(api_url, socket_url):
    assert events_out_url(api_url) == socket_url


@pytest.mark.parametrize(
    "kwargs, kind",
    [
        (dict(handshake_status=403), "refused"),
        (dict(handshake_status=502), "error"),
        (dict(auth_failed=True), "refused"),
        (dict(close_code=1008), "refused"),
        (dict(close_code=1008, delivered=True), "server_close"),
        (dict(close_code=1011, asked_for_backfill=True), "backfill_failure"),
        (dict(close_code=1011, asked_for_backfill=False), "server_close"),
        (
            dict(close_code=1011, asked_for_backfill=True, delivered=True),
            "server_close",
        ),
        (dict(close_code=1001), "server_close"),
        (dict(close_code=1006), "error"),
        (dict(), "error"),
    ],
)
def test_close_kind(kwargs, kind):
    arguments = dict(
        handshake_status=None,
        auth_failed=False,
        close_code=None,
        delivered=False,
        asked_for_backfill=False,
    )
    arguments.update(kwargs)
    assert close_kind(**arguments) == kind


class ServerThread:
    """Runs a FakeEventsServer on its own event loop thread."""

    def __init__(self, scripts):
        self.server = FakeEventsServer()
        self.server.scripts = scripts
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.server.__aenter__())
        self.ready.set()
        self.loop.run_forever()

    def __enter__(self):
        self.thread.start()
        self.ready.wait(5)
        return self.server

    def __exit__(self, *exc):
        asyncio.run_coroutine_threadsafe(self.server.__aexit__(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


def _register_oss_api(url, stream_out_enabled=True):
    responses.add(
        responses.GET,
        f"{url}/admin/settings",
        json={"server": {"events": {"stream_out_enabled": stream_out_enabled}}},
    )

    def listing(items):
        def callback(request):
            body = json.loads(request.body)
            return (200, {}, json.dumps(items if body.get("offset") == 0 else []))

        return callback

    responses.add_callback(
        responses.POST,
        f"{url}/deployments/filter",
        callback=listing(
            [
                {
                    "id": "d1",
                    "name": "recorded-deployment",
                    "flow_id": "f1",
                    "work_pool_name": "recorded-pool",
                    "work_queue_name": "default",
                },
                {
                    "id": "d2",
                    "name": "quiet-deployment",
                    "flow_id": "f1",
                    "work_pool_name": "recorded-pool",
                    "work_queue_name": "default",
                },
            ]
        ),
    )
    responses.add_callback(
        responses.POST,
        f"{url}/flows/filter",
        callback=listing([{"id": "f1", "name": "recorded-flow"}]),
    )
    for path in ("work_pools/filter", "work_queues/filter"):
        responses.add_callback(responses.POST, f"{url}/{path}", callback=listing([]))
    for path in ("deployments/count", "flows/count"):
        responses.add(responses.POST, f"{url}/{path}", json=1)
    responses.add(responses.POST, f"{url}/flow_runs/filter-minimal", status=404)
    responses.add_callback(
        responses.POST,
        f"{url}/flow_runs/filter",
        callback=listing(
            [
                {
                    "id": "r1",
                    "deployment_id": "d1",
                    "flow_id": "f1",
                    "state_type": "RUNNING",
                    "state_name": "Running",
                    "work_queue_name": "default",
                    "start_time": "2026-11-17T12:00:00Z",
                }
            ]
        ),
    )


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.02)


def _exporter(port, registry):
    url = f"http://127.0.0.1:{port}/api"
    config = Config.from_env(
        {"PREFECT_API_URL": url, "FAILED_RUNS_OFFSET_MINUTES": "0"}
    )
    return url, Exporter(
        config,
        registry,
        logging.getLogger("test"),
        stream_settings_overrides=dict(delivering_grace=0.2),
    )


@responses.activate
def test_exporter_counts_stream_events_on_series_the_inventory_created():
    async def send_events(ws, filter_message):
        for event in EVENTS:
            await ws.send(event_message(event))
        await ws.wait_closed()

    registry = CollectorRegistry()
    with ServerThread([send_events]) as server:
        url = f"http://127.0.0.1:{server.port}/api"
        _register_oss_api(url)
        _, exporter = _exporter(server.port, registry)
        exporter.start()
        try:

            def value(name, **labels):
                return registry.get_sample_value(name, labels)

            deployed = {
                "deployment_name": "recorded-deployment",
                "flow_name": "recorded-flow",
                "work_pool_name": "recorded-pool",
                "work_queue_name": "default",
            }
            _wait_for(
                lambda: value(
                    "prefect_flow_runs_terminal_total",
                    **deployed,
                    state_type="COMPLETED",
                    state_name="Completed",
                )
                == 3
            )
            _wait_for(
                lambda: value("prefect_exporter_poll_success", poller="runs") == 1
                and value("prefect_exporter_poll_success", poller="inventory") == 1
            )
            assert (
                value(
                    "prefect_flow_runs_terminal_total",
                    **deployed,
                    state_type="CRASHED",
                    state_name="Crashed",
                )
                == 1
            )
            assert (
                value(
                    "prefect_flow_runs_current",
                    deployment_name="recorded-deployment",
                    flow_name="recorded-flow",
                    work_queue_name="default",
                    state_type="RUNNING",
                    state_name="Running",
                )
                == 1
            )
            assert (
                value(
                    "prefect_flow_runs_terminal_total",
                    **{**deployed, "deployment_name": "quiet-deployment"},
                    state_type="FAILED",
                    state_name="Failed",
                )
                == 0
            )
            assert value("prefect_exporter_stream_connected") == 1
            assert value("prefect_exporter_stream_refused") == 0
            assert server.filters[0]["backfill"] is False
            body = generate_latest(registry).decode()
            assert "prefect_info_deployment{" in body
        finally:
            exporter.stop()
        assert not exporter.stream_thread.is_alive()


@responses.activate
def test_open_source_server_with_the_stream_off_is_reported_refused():
    registry = CollectorRegistry()
    with ServerThread([]) as server:
        url = f"http://127.0.0.1:{server.port}/api"
        _register_oss_api(url, stream_out_enabled=False)
        _, exporter = _exporter(server.port, registry)
        exporter.start()
        try:
            _wait_for(lambda: len(server.filters) == 1)
            assert registry.get_sample_value("prefect_exporter_stream_refused") == 1
        finally:
            exporter.stop()


def test_cloud_does_not_read_server_settings(monkeypatch):
    called = []
    monkeypatch.setattr(
        "metrics.exporter.PrefectAdmin.stream_out_enabled",
        lambda self: called.append(1),
    )

    exporter = Exporter(
        Config.from_env({"PREFECT_API_URL": CLOUD_URL, "PREFECT_API_KEY": "k"}),
        CollectorRegistry(),
        logging.getLogger("test"),
    )

    assert called == []
    assert exporter.stream.read_stream_out_enabled is None
    assert exporter.stream.settings.backfill_window == 120.0
    assert exporter.stream.settings.token == "k"
    assert exporter.stream.url.startswith("wss://api.prefect.cloud/")


@responses.activate
@pytest.mark.parametrize(
    "reply",
    [
        dict(body="<html>proxy</html>", content_type="text/html"),
        dict(json=["not", "a", "mapping"]),
        dict(json={"server": "unexpected"}),
    ],
)
def test_unreadable_server_settings_read_as_unknown(reply):
    url = "http://prefect.test/api"
    responses.add(responses.GET, f"{url}/admin/settings", **reply)

    exporter = Exporter(
        Config.from_env({"PREFECT_API_URL": url}),
        CollectorRegistry(),
        logging.getLogger("test"),
    )

    assert exporter.stream.read_stream_out_enabled() is None


@responses.activate
def test_building_the_exporter_sends_no_api_request():
    Exporter(
        Config.from_env({"PREFECT_API_URL": "http://prefect.test/api"}),
        CollectorRegistry(),
        logging.getLogger("test"),
    )

    assert len(responses.calls) == 0


def test_stream_thread_restarts_a_stream_that_raised(monkeypatch):
    monkeypatch.setattr("metrics.exporter.STREAM_RESTART_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(
        "metrics.exporter.PrefectAdmin.stream_out_enabled", lambda self: True
    )
    exporter = Exporter(
        Config.from_env({}), CollectorRegistry(), logging.getLogger("test")
    )
    runs = []

    async def flaky_run():
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError("escaped")
        exporter.stop_event.set()

    monkeypatch.setattr(exporter.stream, "run", flaky_run)
    exporter.stream_thread.start()
    exporter.stream_thread.join(5)

    assert len(runs) == 2
    assert not exporter.stream_thread.is_alive()
