import json
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from metrics.stream.classifier import FlowRunEventClassifier
from metrics.stream.counters import FlowRunStreamMetrics

FIXTURES = Path(__file__).parent / "fixtures" / "events"

DEPLOYMENT = {
    "id": "d1",
    "name": "recorded-deployment",
    "flow_id": "f1",
    "work_pool_name": "recorded-pool",
    "work_queue_name": "default",
}
FLOWS = [
    {"id": "f1", "name": "recorded-flow"},
    {"id": "f2", "name": "recorded-flow-no-deployment"},
]
STATES = {
    ("COMPLETED", "Completed"),
    ("COMPLETED", "Cached"),
    ("FAILED", "Failed"),
    ("FAILED", "TimedOut"),
    ("CRASHED", "Crashed"),
    ("CANCELLED", "Cancelled"),
}


@pytest.fixture
def registry():
    return CollectorRegistry()


def _terminal_series(registry):
    return {
        tuple(sorted(s.labels.items())): s.value
        for metric in registry.collect()
        if metric.name == "prefect_flow_runs_terminal"
        for s in metric.samples
        if s.name == "prefect_flow_runs_terminal_total"
    }


def _series_labels(deployment, flow, pool, queue, state_type, state_name):
    return tuple(
        sorted(
            {
                "deployment_name": deployment,
                "flow_name": flow,
                "work_pool_name": pool,
                "work_queue_name": queue,
                "state_type": state_type,
                "state_name": state_name,
            }.items()
        )
    )


def test_inventory_creates_six_zero_series_per_deployment_and_undeployed_flow(
    registry,
):
    FlowRunStreamMetrics(registry).precreate([DEPLOYMENT], FLOWS)

    expected = {
        _series_labels(
            "recorded-deployment", "recorded-flow", "recorded-pool", "default", t, n
        ): 0.0
        for t, n in STATES
    } | {
        _series_labels("", "recorded-flow-no-deployment", "", "", t, n): 0.0
        for t, n in STATES
    }
    assert _terminal_series(registry) == expected


def test_zero_series_expose_a_created_timestamp(registry):
    FlowRunStreamMetrics(registry).precreate([DEPLOYMENT], FLOWS)

    body = generate_latest(registry).decode()

    created = [
        line
        for line in body.splitlines()
        if line.startswith("prefect_flow_runs_terminal_created{")
    ]
    assert len(created) == 12


def test_histogram_series_are_not_precreated(registry):
    FlowRunStreamMetrics(registry).precreate([DEPLOYMENT], FLOWS)

    assert (
        "prefect_flow_run_duration_seconds_bucket"
        not in generate_latest(registry).decode()
    )


def test_deployment_whose_flow_is_unknown_gets_no_series(registry):
    FlowRunStreamMetrics(registry).precreate([DEPLOYMENT], [])

    assert _terminal_series(registry) == {}


def test_recorded_events_land_on_the_precreated_series(registry):
    metrics = FlowRunStreamMetrics(registry)
    metrics.precreate([DEPLOYMENT], FLOWS)
    classifier = FlowRunEventClassifier()

    for event in json.loads((FIXTURES / "oss_flow_run_states.json").read_text()):
        metrics.record(classifier.classify(event))

    series = _terminal_series(registry)
    deployed = ("recorded-deployment", "recorded-flow", "recorded-pool", "default")
    assert series[_series_labels(*deployed, "COMPLETED", "Completed")] == 3
    assert series[_series_labels(*deployed, "CANCELLED", "Cancelled")] == 2
    assert series[_series_labels(*deployed, "FAILED", "Exploded")] == 1
    assert (
        series[
            _series_labels(
                "", "recorded-flow-no-deployment", "", "", "COMPLETED", "Completed"
            )
        ]
        == 1
    )
    # Six pre-created states for each of two label sets, plus the custom name.
    assert len(series) == 13


def test_durations_are_observed_once_per_counted_terminal(registry):
    metrics = FlowRunStreamMetrics(registry)
    classifier = FlowRunEventClassifier()
    events = json.loads((FIXTURES / "oss_flow_run_states.json").read_text())

    for event in events + events:
        metrics.record(classifier.classify(event))

    def count(state_type):
        return registry.get_sample_value(
            "prefect_flow_run_duration_seconds_count",
            {
                "deployment_name": "recorded-deployment",
                "flow_name": "recorded-flow",
                "state_type": state_type,
            },
        )

    # Left RUNNING: completed, cached, rerun episode 2, retry; timed-out,
    # failed episode 1, custom name; crashed. The cancelled runs did not.
    assert count("COMPLETED") == 4
    assert count("FAILED") == 3
    assert count("CRASHED") == 1
    assert count("CANCELLED") is None
