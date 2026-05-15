import logging
from unittest.mock import MagicMock

import pytest
import responses

from metrics.healthz import PrefectHealthz


def _make():
    return PrefectHealthz(
        url="http://prefect.test/api",
        headers={"accept": "application/json"},
        max_retries=3,
        logger=logging.getLogger("test"),
    )


@responses.activate
def test_health_503_with_retry_after_exits_immediately(monkeypatch):
    sleep_mock = MagicMock()
    monkeypatch.setattr("metrics.healthz.time.sleep", sleep_mock)

    responses.add(
        responses.GET,
        "http://prefect.test/api/health",
        status=503,
        headers={"Retry-After": "1200", "Prefect-Maintenance": "true"},
        json={},
    )

    with pytest.raises(SystemExit):
        _make().get_health_check()

    assert sleep_mock.call_count == 0
    assert len(responses.calls) == 1


@responses.activate
def test_health_success(monkeypatch):
    monkeypatch.setattr("metrics.healthz.time.sleep", MagicMock())

    responses.add(
        responses.GET,
        "http://prefect.test/api/health",
        status=200,
        json={"ok": True},
    )

    _make().get_health_check()
    assert len(responses.calls) == 1
