import copy
import json
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from metrics.stream.classifier import FlowRunEventClassifier, TerminalLabels

FIXTURES = Path(__file__).parent / "fixtures" / "events"
DAY = 24 * 3600


def _oss_events():
    """Flow-run events recorded from a local open-source Prefect server."""
    return json.loads((FIXTURES / "oss_flow_run_states.json").read_text())


def _run_events(name):
    return [e for e in _oss_events() if e["resource"]["prefect.resource.name"] == name]


def _cloud_shaped(event):
    """
    The same event as Prefect Cloud builds it: the prior state in the payload
    carries its timestamp and id, the resource carries `prefect.audit`, and an
    actor may be related.
    """
    event = copy.deepcopy(event)
    event["resource"]["prefect.audit"] = "false"
    event["related"].append(
        {
            "prefect.resource.id": f"prefect-cloud.actor.{uuid.uuid4()}",
            "prefect.resource.role": "actor",
        }
    )
    return event


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def classifier(clock):
    return FlowRunEventClassifier(clock=clock)


def _labels(state_type, state_name, deployment=True):
    if deployment:
        return TerminalLabels(
            "recorded-deployment",
            "recorded-flow",
            "recorded-pool",
            "default",
            state_type,
            state_name,
        )
    return TerminalLabels(
        "", "recorded-flow-no-deployment", "", "", state_type, state_name
    )


def _ts(raw):
    return datetime.fromisoformat(raw)


def test_recorded_server_events_count_each_terminal_state_an_episode_entered(
    classifier,
):
    results = [classifier.classify(e) for e in _oss_events()]

    counted = Counter(r.labels for r in results if r.outcome == "counted")
    assert counted == {
        _labels("COMPLETED", "Completed"): 3,
        _labels("COMPLETED", "Cached"): 1,
        _labels("FAILED", "Failed"): 1,
        _labels("FAILED", "TimedOut"): 1,
        _labels("FAILED", "Exploded"): 1,
        _labels("CRASHED", "Crashed"): 1,
        _labels("CANCELLED", "Cancelled"): 2,
        _labels("COMPLETED", "Completed", deployment=False): 1,
    }
    assert Counter(r.outcome for r in results) == {
        "counted": 11,
        "duplicate": 1,
        "ignored": 22,
    }
    assert not any(r.missing_run_count for r in results)


def test_second_cancelled_event_of_one_episode_is_a_duplicate(classifier):
    outcomes = [
        classifier.classify(e).outcome for e in _run_events("cancelled-before-running")
    ]

    assert outcomes == ["ignored", "counted", "duplicate"]


def test_crashed_then_cancelled_counts_in_both_states(classifier):
    results = [classifier.classify(e) for e in _run_events("crashed-then-cancelled")]

    assert [r.labels.state_type for r in results if r.outcome == "counted"] == [
        "CRASHED",
        "CANCELLED",
    ]


def test_each_episode_of_a_rerun_counts(classifier):
    results = [classifier.classify(e) for e in _run_events("failed-then-rerun")]

    assert [
        (r.labels.state_type, r.labels.state_name)
        for r in results
        if r.outcome == "counted"
    ] == [("FAILED", "Failed"), ("COMPLETED", "Completed")]


def test_terminal_is_read_from_the_state_type_not_the_event_name(classifier):
    [_, _, timed_out] = _run_events("timed-out")
    renamed = copy.deepcopy(timed_out)
    renamed["event"] = "prefect.flow-run.Completed"

    result = classifier.classify(renamed)

    assert result.outcome == "counted"
    assert result.labels.state_type == "FAILED"
    assert result.labels.state_name == "TimedOut"


def test_copies_inside_the_memory_are_duplicates_and_after_it_count_again(
    classifier, clock
):
    [*_, completed] = _run_events("completed")

    assert classifier.classify(completed).outcome == "counted"
    clock.now += 2
    assert classifier.classify(completed).outcome == "duplicate"
    clock.now += 4 * 3600
    assert classifier.classify(completed).outcome == "duplicate"
    clock.now = DAY + 1
    assert classifier.classify(completed).outcome == "counted"


def test_duplicate_memory_length_is_configurable(clock):
    classifier = FlowRunEventClassifier(duplicate_memory_seconds=60, clock=clock)
    [*_, completed] = _run_events("completed")

    classifier.classify(completed)
    clock.now = 61

    assert classifier.classify(completed).outcome == "counted"


def test_missing_run_count_counts_as_run_count_zero(classifier):
    [*_, completed] = _run_events("completed")
    without = copy.deepcopy(completed)
    del without["resource"]["prefect.run-count"]
    zero = copy.deepcopy(completed)
    zero["resource"]["prefect.run-count"] = "0"

    first = classifier.classify(without)
    second = classifier.classify(zero)

    assert (first.outcome, first.missing_run_count) == ("counted", True)
    assert (second.outcome, second.missing_run_count) == ("duplicate", False)


def test_non_terminal_and_non_flow_run_events_are_ignored(classifier):
    [scheduled, pending, running, _] = _run_events("completed")
    task_run = copy.deepcopy(_run_events("completed")[-1])
    task_run["resource"]["prefect.resource.id"] = "prefect.task-run.abc"
    no_state = copy.deepcopy(_run_events("completed")[-1])
    del no_state["resource"]["prefect.state-type"]

    for event in (scheduled, pending, running, task_run, no_state):
        result = classifier.classify(event)
        assert (result.outcome, result.missing_run_count) == ("ignored", False)


def test_duration_on_an_open_source_server_comes_from_the_running_event(
    classifier,
):
    events = _run_events("completed")
    running, completed = events[2], events[3]

    results = [classifier.classify(e) for e in events]

    expected = (
        _ts(completed["resource"]["prefect.state-timestamp"])
        - _ts(running["resource"]["prefect.state-timestamp"])
    ).total_seconds()
    assert results[-1].duration_seconds == pytest.approx(expected)
    assert expected > 0


def test_in_process_retry_reports_the_last_attempt(classifier):
    events = _run_events("in-process-retry")
    retrying, completed = events[3], events[4]
    assert retrying["resource"]["prefect.state-name"] == "Retrying"

    results = [classifier.classify(e) for e in events]

    expected = (
        _ts(completed["resource"]["prefect.state-timestamp"])
        - _ts(retrying["resource"]["prefect.state-timestamp"])
    ).total_seconds()
    assert results[-1].duration_seconds == pytest.approx(expected)


def test_duration_on_cloud_comes_from_the_prior_state_in_the_payload(classifier):
    [*_, completed] = _run_events("completed")
    event = _cloud_shaped(completed)
    event["payload"]["initial_state"]["timestamp"] = "2026-11-17T17:00:00+00:00"
    event["resource"]["prefect.state-timestamp"] = "2026-11-17T17:01:30+00:00"

    result = classifier.classify(event)

    assert result.outcome == "counted"
    assert result.labels == _labels("COMPLETED", "Completed")
    assert result.duration_seconds == 90.0


def test_no_duration_when_the_run_did_not_leave_running(classifier):
    results = [classifier.classify(e) for e in _run_events("cancelled-before-running")]
    [*_, crashed, cancelled] = [
        classifier.classify(e) for e in _run_events("crashed-then-cancelled")
    ]
    [*_, cancelling_completed] = _run_events("completed")
    cancelled_from_cancelling = _cloud_shaped(cancelling_completed)
    cancelled_from_cancelling["resource"]["prefect.state-type"] = "CANCELLED"
    cancelled_from_cancelling["payload"]["initial_state"] = {
        "type": "CANCELLING",
        "name": "Cancelling",
        "timestamp": "2026-11-17T17:00:00+00:00",
    }

    assert results[1].duration_seconds is None
    assert crashed.duration_seconds is not None
    assert cancelled.duration_seconds is None
    assert classifier.classify(cancelled_from_cancelling).duration_seconds is None


def test_no_duration_when_the_running_event_was_never_received(classifier):
    [*_, completed] = _run_events("completed")

    result = classifier.classify(completed)

    assert result.outcome == "counted"
    assert result.duration_seconds is None


def test_running_times_expire_after_seven_days(classifier, clock):
    events = _run_events("completed")
    classifier.classify(events[2])
    assert len(classifier.running_times) == 1

    clock.now = 7 * DAY + 1

    assert len(classifier.running_times) == 0
    assert classifier.classify(events[3]).duration_seconds is None


def test_running_time_is_released_by_the_terminal_event(classifier):
    for event in _run_events("completed"):
        classifier.classify(event)

    assert len(classifier.running_times) == 0


def test_a_second_name_of_the_same_state_type_is_a_duplicate(classifier):
    [*_, completed] = _run_events("completed")
    cached = copy.deepcopy(completed)
    cached["resource"]["prefect.state-name"] = "Cached"

    first = classifier.classify(completed)
    second = classifier.classify(cached)

    assert first.labels.state_name == "Completed"
    assert second.outcome == "duplicate"


def test_the_same_terminal_state_in_two_episodes_counts_twice(classifier):
    [*_, completed] = _run_events("completed")
    next_episode = copy.deepcopy(completed)
    next_episode["resource"]["prefect.run-count"] = "2"

    assert classifier.classify(completed).outcome == "counted"
    assert classifier.classify(next_episode).outcome == "counted"
