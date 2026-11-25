import http.client
from unittest.mock import MagicMock, create_autospec
from wsgiref.simple_server import WSGIServer

import pytest
from prometheus_client import CollectorRegistry
from prometheus_client.core import GaugeMetricFamily

import main
from metrics.exporter import Exporter


def test_metrics_are_served_before_the_exporter_is_built(monkeypatch):
    calls = MagicMock()
    httpd = create_autospec(WSGIServer, instance=True)
    start_http_server = create_autospec(
        main.start_http_server, return_value=(httpd, MagicMock())
    )
    exporter = create_autospec(Exporter)
    calls.attach_mock(start_http_server, "start_http_server")
    calls.attach_mock(exporter, "Exporter")
    monkeypatch.setattr(main, "start_http_server", start_http_server)
    monkeypatch.setattr(main, "Exporter", exporter)
    monkeypatch.setattr(main.signal, "signal", MagicMock())
    shutdown = MagicMock()
    monkeypatch.setattr(main.threading, "Event", MagicMock(return_value=shutdown))
    monkeypatch.setenv("METRICS_PORT", "8123")
    monkeypatch.setenv("METRICS_ADDR", "127.0.0.1")

    main.metrics()

    names = [name for name, _, _ in calls.mock_calls]
    assert names.index("start_http_server") < names.index("Exporter")
    start_http_server.assert_called_once_with(8123, "127.0.0.1")
    shutdown.wait.assert_called_once()
    exporter.return_value.start.assert_called_once_with()
    exporter.return_value.stop.assert_called_once_with()


class RecordingCollector:
    def __init__(self):
        self.collections = 0

    def collect(self):
        self.collections += 1
        yield GaugeMetricFamily("recorded", "A recorded gauge", value=7)


@pytest.fixture
def collector():
    return RecordingCollector()


@pytest.fixture
def request_exporter(monkeypatch, collector):
    """Run main.metrics() on an ephemeral port and return a request function."""
    registry = CollectorRegistry(auto_describe=False)
    registry.register(collector)
    start_http_server = main.start_http_server
    servers = []

    def start_on_ephemeral_port(port, addr):
        server = start_http_server(0, "127.0.0.1", registry)
        servers.append(server)
        return server

    monkeypatch.setattr(main, "start_http_server", start_on_ephemeral_port)
    monkeypatch.setattr(main, "Exporter", create_autospec(Exporter))
    monkeypatch.setattr(main.signal, "signal", MagicMock())
    # HTTPServer uses threading.Event too, so replace the name in main only.
    monkeypatch.setattr(main, "threading", MagicMock())

    def request(method, path):
        connection = http.client.HTTPConnection(
            "127.0.0.1", servers[0][0].server_port, timeout=5
        )
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    try:
        main.metrics()
        yield request
    finally:
        for httpd, thread in servers:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


@pytest.mark.parametrize("path", ["/health", "/health?x=1"])
def test_health_answers_ok_without_collecting_metrics(
    request_exporter, collector, path
):
    assert request_exporter("GET", path) == (
        200,
        "text/plain; charset=utf-8",
        b"OK",
    )
    assert collector.collections == 0


@pytest.mark.parametrize("path", ["/metrics", "/", "/health/", "/healthz"])
def test_other_paths_serve_metrics(request_exporter, collector, path):
    status, _, body = request_exporter("GET", path)

    assert status == 200
    assert b"recorded 7.0" in body
    assert collector.collections == 1


@pytest.mark.parametrize("method", ["POST", "HEAD"])
def test_health_refuses_other_methods(request_exporter, collector, method):
    status, _, _ = request_exporter(method, "/health")

    assert status == 405
    assert collector.collections == 0


def test_health_answers_options_with_an_empty_body(request_exporter, collector):
    status, _, body = request_exporter("OPTIONS", "/health")

    assert (status, body) == (200, b"")
    assert collector.collections == 0
