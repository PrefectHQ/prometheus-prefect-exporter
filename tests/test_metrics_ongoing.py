"""Tests for the prefect_flow_runs_ongoing_run_time metric.

Covers the correctness fixes from PLA-2754:
  1. No duplicate timeseries (flow_run_id uniquifies same flow/deployment/state).
  2. A naive (tz-less) start_time does not blank the whole scrape.
  3. Future-dated runs never emit a negative run_time.
  4. A null start_time emits no series (no misleading 0).
  5. A missing state_name renders as "null", not "None".
  6. enable_flow_run_name_label adds flow_run_name alongside flow_run_id.
"""

import json
import logging

import responses

from metrics.metrics import PrefectMetrics

URL = "http://prefect.test/api"

DEPLOYMENT_ID = "dep-1"
FLOW_ID = "flow-1"


def _make(enable_flow_run_name_label=False):
    return PrefectMetrics(
        url=URL,
        headers={"accept": "application/json"},
        offset_minutes=3,
        # 0 disables the failed-runs fetch, so no extra endpoint to mock.
        failed_runs_offset_minutes=0,
        failed_runs_limit=10,
        max_retries=3,
        client_id="test-client-id",
        csrf_enabled=False,
        logger=logging.getLogger("test"),
        enable_pagination=False,
        pagination_limit=200,
        enable_flow_run_name_label=enable_flow_run_name_label,
    )


def _register_endpoints(ongoing_runs):
    """Mock every /filter endpoint collect() touches.

    flow_runs/filter is hit three times with different bodies (recent, all,
    ongoing); a callback routes by request body so only the ongoing query
    returns the supplied runs.
    """
    responses.add(
        responses.POST,
        f"{URL}/deployments/filter",
        json=[{"id": DEPLOYMENT_ID, "name": "my-deployment", "flow_id": FLOW_ID}],
    )
    responses.add(
        responses.POST,
        f"{URL}/flows/filter",
        json=[{"id": FLOW_ID, "name": "my-flow"}],
    )
    responses.add(
        responses.POST,
        f"{URL}/work_pools/filter",
        json=[],
    )
    responses.add(
        responses.POST,
        f"{URL}/work_queues/filter",
        json=[],
    )

    def flow_runs_callback(request):
        body = json.loads(request.body)
        flow_runs_filter = body.get("flow_runs", {})
        # The ongoing query is the only one filtering on a null end_time.
        is_ongoing = "is_null_" in flow_runs_filter.get("end_time", {})
        payload = ongoing_runs if is_ongoing else []
        return (200, {}, json.dumps(payload))

    responses.add_callback(
        responses.POST,
        f"{URL}/flow_runs/filter",
        callback=flow_runs_callback,
        content_type="application/json",
    )


def _ongoing_family(metrics):
    """Return the prefect_flow_runs_ongoing_run_time family from collect()."""
    for family in metrics.collect():
        if family.name == "prefect_flow_runs_ongoing_run_time":
            return family
    raise AssertionError("prefect_flow_runs_ongoing_run_time not yielded")


def _samples(family):
    """List of (labels_dict, value) for a metric family."""
    return [(dict(s.labels), s.value) for s in family.samples]


@responses.activate
def test_no_duplicate_timeseries():
    """Two RUNNING runs of the same flow/deployment/state are distinct series."""
    _register_endpoints(
        [
            {
                "id": "run-a",
                "deployment_id": DEPLOYMENT_ID,
                "flow_id": FLOW_ID,
                "state_name": "Running",
                "start_time": "2026-06-01T10:00:00+00:00",
            },
            {
                "id": "run-b",
                "deployment_id": DEPLOYMENT_ID,
                "flow_id": FLOW_ID,
                "state_name": "Running",
                "start_time": "2026-06-01T10:00:00+00:00",
            },
        ]
    )

    samples = _samples(_ongoing_family(_make()))

    assert len(samples) == 2
    run_ids = {labels["flow_run_id"] for labels, _ in samples}
    assert run_ids == {"run-a", "run-b"}
    # Label tuples must be unique so Prometheus accepts the scrape.
    label_tuples = [tuple(sorted(labels.items())) for labels, _ in samples]
    assert len(set(label_tuples)) == len(label_tuples)


@responses.activate
def test_naive_start_time_does_not_blank_scrape():
    """A tz-naive start_time must not raise out of collect() and zero all metrics."""
    _register_endpoints(
        [
            {
                "id": "run-naive",
                "deployment_id": DEPLOYMENT_ID,
                "flow_id": FLOW_ID,
                "state_name": "Running",
                # No tz offset: previously caused TypeError on subtraction.
                "start_time": "2026-06-01T10:00:00",
            }
        ]
    )

    families = list(_make().collect())
    names = {f.name for f in families}
    # The scrape is not blanked: other metrics are still present.
    assert "prefect_info_deployment" in names
    assert "prefect_flow_runs_ongoing_run_time" in names

    family = next(f for f in families if f.name == "prefect_flow_runs_ongoing_run_time")
    samples = _samples(family)
    assert len(samples) == 1
    labels, value = samples[0]
    assert labels["flow_run_id"] == "run-naive"
    assert value >= 0


@responses.activate
def test_future_start_time_not_negative():
    """A future-dated SCHEDULED run reports run_time clamped to >= 0."""
    _register_endpoints(
        [
            {
                "id": "run-future",
                "deployment_id": DEPLOYMENT_ID,
                "flow_id": FLOW_ID,
                "state_name": "Scheduled",
                "start_time": "2099-01-01T00:00:00+00:00",
            }
        ]
    )

    samples = _samples(_ongoing_family(_make()))
    assert len(samples) == 1
    _, value = samples[0]
    assert value == 0.0


@responses.activate
def test_null_start_time_skipped():
    """A run with no start_time emits no series (instead of a misleading 0)."""
    _register_endpoints(
        [
            {
                "id": "run-pending",
                "deployment_id": DEPLOYMENT_ID,
                "flow_id": FLOW_ID,
                "state_name": "Pending",
                "start_time": None,
            }
        ]
    )

    samples = _samples(_ongoing_family(_make()))
    assert samples == []


@responses.activate
def test_missing_state_name_renders_null():
    """A run missing state_name uses the string 'null', not 'None'."""
    _register_endpoints(
        [
            {
                "id": "run-nostate",
                "deployment_id": DEPLOYMENT_ID,
                "flow_id": FLOW_ID,
                # state_name omitted entirely
                "start_time": "2026-06-01T10:00:00+00:00",
            }
        ]
    )

    samples = _samples(_ongoing_family(_make()))
    assert len(samples) == 1
    labels, _ = samples[0]
    assert labels["state_name"] == "null"


@responses.activate
def test_flow_run_name_label_added():
    """enable_flow_run_name_label adds flow_run_name alongside flow_run_id."""
    _register_endpoints(
        [
            {
                "id": "run-named",
                "name": "ambitious-aardvark",
                "deployment_id": DEPLOYMENT_ID,
                "flow_id": FLOW_ID,
                "state_name": "Running",
                "start_time": "2026-06-01T10:00:00+00:00",
            }
        ]
    )

    samples = _samples(_ongoing_family(_make(enable_flow_run_name_label=True)))
    assert len(samples) == 1
    labels, _ = samples[0]
    assert labels["flow_run_id"] == "run-named"
    assert labels["flow_run_name"] == "ambitious-aardvark"
