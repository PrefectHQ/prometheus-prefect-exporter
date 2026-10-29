import logging
import threading
import time

import responses

from metrics.metrics import PrefectMetrics

URL = "http://prefect.test/api"
TIMESTAMP_METRIC = "prefect_exporter_last_successful_collection_timestamp_seconds"


def _make(collection_interval_seconds=60, **overrides):
    kwargs = {
        "url": URL,
        "headers": {"accept": "application/json"},
        "offset_minutes": 3,
        "failed_runs_offset_minutes": 10080,
        "failed_runs_limit": 10,
        "max_retries": 1,
        "client_id": "test-client-id",
        "csrf_enabled": False,
        "logger": logging.getLogger("test"),
        "enable_pagination": False,
        "pagination_limit": 200,
        "collection_interval_seconds": collection_interval_seconds,
    }
    kwargs.update(overrides)
    return PrefectMetrics(**kwargs)


def _register_endpoints():
    responses.add(
        responses.POST,
        f"{URL}/deployments/filter",
        json=[{"id": "dep-1", "name": "my-deployment", "flow_id": "flow-1"}],
    )
    responses.add(
        responses.POST,
        f"{URL}/flows/filter",
        json=[{"id": "flow-1", "name": "my-flow"}],
    )
    responses.add(responses.POST, f"{URL}/flow_runs/filter", json=[])
    responses.add(responses.POST, f"{URL}/work_pools/filter", json=[])
    responses.add(
        responses.POST,
        f"{URL}/work_queues/filter",
        json=[{"id": "wq-1", "name": "default"}],
    )
    responses.add(
        responses.GET,
        f"{URL}/work_queues/wq-1/status",
        json={"healthy": True, "late_runs_count": 0},
    )


def _samples(families):
    return {
        (s.name, tuple(sorted(s.labels.items())), s.value)
        for family in families
        for s in family.samples
    }


@responses.activate
def test_collect_before_first_collection_yields_nothing():
    assert list(_make().collect()) == []
    assert len(responses.calls) == 0


@responses.activate
def test_collect_serves_snapshot_without_calling_api():
    _register_endpoints()
    collector = _make()
    collector.collect_once()
    calls_after_collection = len(responses.calls)
    assert calls_after_collection > 0

    first = list(collector.collect())
    second = list(collector.collect())

    assert len(responses.calls) == calls_after_collection
    assert _samples(first) == _samples(second)
    names = {family.name for family in first}
    assert "prefect_deployments_total" in names
    assert "prefect_info_work_queues" in names


@responses.activate
def test_snapshot_matches_synchronous_output():
    _register_endpoints()
    background = _make()
    background.collect_once()
    background_families = [
        f for f in background.collect() if f.name != TIMESTAMP_METRIC
    ]

    synchronous = list(_make(collection_interval_seconds=0).collect())

    assert TIMESTAMP_METRIC not in {f.name for f in synchronous}
    assert _samples(background_families) == _samples(synchronous)


@responses.activate
def test_timestamp_gauge_reports_last_successful_collection():
    _register_endpoints()
    collector = _make()

    before = time.time()
    collector.collect_once()
    after = time.time()

    (gauge,) = [f for f in collector.collect() if f.name == TIMESTAMP_METRIC]
    (sample,) = gauge.samples
    assert before <= sample.value <= after


@responses.activate
def test_failed_collection_keeps_previous_snapshot(caplog):
    _register_endpoints()
    collector = _make()
    collector.collect_once()
    previous = list(collector.collect())

    # A non-JSON body raises out of the collection instead of being swallowed
    # as a failed request.
    responses.replace(responses.POST, f"{URL}/deployments/filter", body="not json")
    with caplog.at_level(logging.ERROR):
        collector.collect_once()

    assert "serving the previous snapshot" in caplog.text
    assert _samples(collector.collect()) == _samples(previous)


@responses.activate
def test_run_collection_loop_collects_until_stopped():
    _register_endpoints()
    collector = _make()
    stop = threading.Event()
    stop.set()

    collector.run_collection_loop(stop)

    assert TIMESTAMP_METRIC in {f.name for f in collector.collect()}
