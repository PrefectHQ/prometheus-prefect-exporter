from unittest.mock import MagicMock, create_autospec

import main
from metrics.exporter import Exporter


def test_metrics_are_served_before_the_exporter_is_built(monkeypatch):
    calls = MagicMock()
    start_http_server = create_autospec(main.start_http_server)
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
