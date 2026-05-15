import logging
from unittest.mock import MagicMock

import pytest
import requests
import responses

from metrics.metrics import PrefectMetrics


def _make():
    return PrefectMetrics(
        url="http://prefect.test/api",
        headers={"accept": "application/json"},
        offset_minutes=3,
        failed_runs_offset_minutes=10080,
        failed_runs_limit=10,
        max_retries=3,
        client_id="test-client-id",
        csrf_enabled=True,
        logger=logging.getLogger("test"),
        enable_pagination=False,
        pagination_limit=200,
        enable_flow_run_name_label=False,
    )


@responses.activate
def test_csrf_503_with_retry_after_raises_immediately(monkeypatch):
    sleep_mock = MagicMock()
    monkeypatch.setattr("metrics.metrics.time.sleep", sleep_mock)

    responses.add(
        responses.GET,
        "http://prefect.test/api/csrf-token",
        status=503,
        headers={"Retry-After": "1200", "Prefect-Maintenance": "true"},
        json={},
    )

    with pytest.raises(requests.exceptions.RequestException):
        _make().get_csrf_token()

    assert sleep_mock.call_count == 0
    assert len(responses.calls) == 1
