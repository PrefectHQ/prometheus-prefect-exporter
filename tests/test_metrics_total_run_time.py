"""Tests for the prefect_flow_runs_total_run_time metric.

Two finished runs of one flow inside the offset window must be distinct series:
with only ``flow_name`` as label they share a label tuple with different values,
and Prometheus drops every sample after the first with "Error on ingesting
samples with different value but same timestamp".
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


def _register_endpoints(finished_runs):
    """Mock every /filter endpoint collect() touches.

    flow_runs/filter is hit with several bodies (per-state, all, ongoing); a
    callback routes by request body so only the "all runs" query, the one
    that feeds prefect_flow_runs_total_run_time, returns the supplied runs.
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
        # The all-runs query is the only one filtering on end_time after_.
        is_all_runs = "after_" in flow_runs_filter.get("end_time", {})
        payload = finished_runs if is_all_runs else []
        return (200, {}, json.dumps(payload))

    responses.add_callback(
        responses.POST,
        f"{URL}/flow_runs/filter",
        callback=flow_runs_callback,
        content_type="application/json",
    )


def _total_run_time_family(metrics):
    """Return the prefect_flow_runs_total_run_time family from collect()."""
    for family in metrics.collect():
        if family.name == "prefect_flow_runs_total_run_time":
            return family
    raise AssertionError("prefect_flow_runs_total_run_time not yielded")


def _samples(family):
    """List of (labels_dict, value) for a metric family."""
    return [(dict(s.labels), s.value) for s in family.samples]


def _run(run_id, total_run_time, name=None):
    run = {
        "id": run_id,
        "deployment_id": DEPLOYMENT_ID,
        "flow_id": FLOW_ID,
        "state_name": "Completed",
        "total_run_time": total_run_time,
    }
    if name is not None:
        run["name"] = name
    return run


@responses.activate
def test_runs_of_one_flow_are_distinct_series():
    """Two finished runs of the same flow keep their own value."""
    _register_endpoints([_run("run-a", 12.5), _run("run-b", 30.0)])

    samples = _samples(_total_run_time_family(_make()))

    assert sorted(
        (labels["flow_name"], labels["flow_run_id"], value) for labels, value in samples
    ) == [
        ("my-flow", "run-a", 12.5),
        ("my-flow", "run-b", 30.0),
    ]
    # Label tuples must be unique so Prometheus accepts the scrape.
    label_tuples = [tuple(sorted(labels.items())) for labels, _ in samples]
    assert len(set(label_tuples)) == len(label_tuples)


@responses.activate
def test_flow_run_name_label_is_opt_in():
    """flow_run_name follows ENABLE_FLOW_RUN_NAME_LABEL, as for the ongoing metric."""
    _register_endpoints([_run("run-a", 1.0, name="brave-otter")])

    ((default_labels, _),) = _samples(_total_run_time_family(_make()))
    assert "flow_run_name" not in default_labels

    ((named_labels, _),) = _samples(
        _total_run_time_family(_make(enable_flow_run_name_label=True))
    )
    assert named_labels["flow_run_id"] == "run-a"
    assert named_labels["flow_run_name"] == "brave-otter"
