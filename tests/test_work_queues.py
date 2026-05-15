import logging
import uuid
from unittest.mock import MagicMock

import responses

from metrics.work_queues import PrefectWorkQueues


def _make():
    return PrefectWorkQueues(
        url="http://prefect.test/api",
        headers={"accept": "application/json"},
        max_retries=3,
        logger=logging.getLogger("test"),
        enable_pagination=True,
        pagination_limit=2,
    )


@responses.activate
def test_status_503_with_retry_after_returns_empty(monkeypatch):
    sleep_mock = MagicMock()
    monkeypatch.setattr("metrics.work_queues.time.sleep", sleep_mock)

    queue_id = uuid.uuid4()
    responses.add(
        responses.GET,
        f"http://prefect.test/api/work_queues/{queue_id}/status",
        status=503,
        headers={"Retry-After": "1200", "Prefect-Maintenance": "true"},
        json={},
    )

    result = _make().get_work_queue_status_info(queue_id)
    assert result == {}
    assert sleep_mock.call_count == 0
    assert len(responses.calls) == 1


@responses.activate
def test_status_500_without_retry_after_still_retries(monkeypatch):
    sleep_mock = MagicMock()
    monkeypatch.setattr("metrics.work_queues.time.sleep", sleep_mock)

    queue_id = uuid.uuid4()
    url = f"http://prefect.test/api/work_queues/{queue_id}/status"
    for _ in range(3):
        responses.add(responses.GET, url, status=500, json={})

    result = _make().get_work_queue_status_info(queue_id)
    assert result == {}
    assert len(responses.calls) == 3
    assert sleep_mock.call_count == 2
