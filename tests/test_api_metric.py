import logging
from unittest.mock import MagicMock

import responses

from metrics.api_metric import PrefectApiMetric


def _make(uri="deployments", **overrides):
    kwargs = dict(
        url="http://prefect.test/api",
        headers={"accept": "application/json"},
        max_retries=3,
        logger=logging.getLogger("test"),
        enable_pagination=True,
        pagination_limit=2,
        uri=uri,
    )
    kwargs.update(overrides)
    return PrefectApiMetric(**kwargs)


@responses.activate
def test_maintenance_503_aborts_immediately(monkeypatch):
    sleep_mock = MagicMock()
    monkeypatch.setattr("metrics.api_metric.time.sleep", sleep_mock)

    responses.add(
        responses.POST,
        "http://prefect.test/api/deployments/filter",
        status=503,
        headers={"Retry-After": "1200", "Prefect-Maintenance": "true"},
        json={"detail": "Prefect will retry this request shortly"},
    )

    api = _make()
    result = api._get_with_pagination()

    assert result == []
    # No sleeps. No retries. One call.
    assert sleep_mock.call_count == 0
    assert len(responses.calls) == 1


@responses.activate
def test_partial_results_when_retry_after_hits_mid_pagination(monkeypatch):
    monkeypatch.setattr("metrics.api_metric.time.sleep", MagicMock())

    url = "http://prefect.test/api/deployments/filter"
    responses.add(responses.POST, url, status=200, json=[{"id": "a"}, {"id": "b"}])
    responses.add(
        responses.POST,
        url,
        status=503,
        headers={"Retry-After": "1200", "Prefect-Maintenance": "true"},
        json={"detail": "maintenance"},
    )

    api = _make()
    result = api._get_with_pagination()

    assert result == [{"id": "a"}, {"id": "b"}]
    assert len(responses.calls) == 2


@responses.activate
def test_429_with_retry_after_also_aborts(monkeypatch):
    monkeypatch.setattr("metrics.api_metric.time.sleep", MagicMock())

    responses.add(
        responses.POST,
        "http://prefect.test/api/deployments/filter",
        status=429,
        headers={"Retry-After": "5"},
        json={"detail": "rate limited"},
    )

    api = _make()
    result = api._get_with_pagination()

    assert result == []
    assert len(responses.calls) == 1


@responses.activate
def test_500_without_retry_after_still_retries(monkeypatch):
    sleep_mock = MagicMock()
    monkeypatch.setattr("metrics.api_metric.time.sleep", sleep_mock)

    url = "http://prefect.test/api/deployments/filter"
    for _ in range(3):
        responses.add(responses.POST, url, status=500, json={"err": "boom"})

    api = _make(max_retries=3)
    result = api._get_with_pagination()

    assert result == []
    # 3 attempts, 2 sleeps (between attempts 0->1 and 1->2).
    assert len(responses.calls) == 3
    assert sleep_mock.call_count == 2


@responses.activate
def test_503_without_retry_after_still_retries(monkeypatch):
    """503 alone (no Retry-After header) should NOT trigger the abort path."""
    sleep_mock = MagicMock()
    monkeypatch.setattr("metrics.api_metric.time.sleep", sleep_mock)

    url = "http://prefect.test/api/deployments/filter"
    for _ in range(3):
        responses.add(responses.POST, url, status=503, json={})

    api = _make(max_retries=3)
    result = api._get_with_pagination()

    assert result == []
    assert len(responses.calls) == 3
    assert sleep_mock.call_count == 2
