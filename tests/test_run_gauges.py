import json
import logging
from datetime import datetime, timezone

import responses
from prometheus_client import CollectorRegistry

from metrics.health import ExporterHealth
from metrics.inventory import InventoryNames
from metrics.run_gauges import RunGaugePoller

URL = "http://prefect.test/api"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
NAMES = InventoryNames({"d1": "dep-one"}, {"f1": "flow-one"})


def _run(run_id, state_type, state_name, **fields):
    return {
        "id": run_id,
        "name": f"name-{run_id}",
        "deployment_id": "d1",
        "flow_id": "f1",
        "work_queue_name": "default",
        "state_type": state_type,
        "state_name": state_name,
        **fields,
    }


def _register(runs):
    """Answer each flow-run listing with the given runs of the queried state type."""

    def callback(request):
        body = json.loads(request.body)
        [state_type] = body["flow_runs"]["state"]["type"]["any_"]
        if body["offset"] > 0:
            return (200, {}, "[]")
        return (
            200,
            {},
            json.dumps([r for r in runs if r["state_type"] == state_type]),
        )

    responses.add(responses.POST, f"{URL}/flow_runs/filter-minimal", status=404)
    responses.add_callback(responses.POST, f"{URL}/flow_runs/filter", callback=callback)


def _poller(names=NAMES, flow_run_name=False):
    return RunGaugePoller(
        dict(
            url=URL,
            headers={},
            max_retries=1,
            logger=logging.getLogger("test"),
            enable_pagination=True,
            pagination_limit=200,
            timeout=10,
            health=ExporterHealth(CollectorRegistry()),
        ),
        inventory_names=lambda: names,
        enable_flow_run_name_label=flow_run_name,
        logger=logging.getLogger("test"),
        now=lambda: NOW,
    )


def _samples(result, name):
    [family] = [f for f in result.families if f.name == name]
    return {tuple(sorted(s.labels.items())): s.value for s in family.samples}


@responses.activate
def test_current_counts_runs_by_labels_and_state():
    _register(
        [
            _run("r1", "RUNNING", "Running"),
            _run("r2", "RUNNING", "Running"),
            _run("r3", "RUNNING", "Retrying"),
            _run("r4", "SCHEDULED", "Late"),
            _run("r5", "PAUSED", "Suspended", work_queue_name="other"),
        ]
    )

    result = _poller().poll()

    assert result.complete
    base = {"deployment_name": "dep-one", "flow_name": "flow-one"}

    def key(**labels):
        return tuple(sorted({**base, "work_queue_name": "default", **labels}.items()))

    assert _samples(result, "prefect_flow_runs_current") == {
        key(state_type="RUNNING", state_name="Running"): 2,
        key(state_type="RUNNING", state_name="Retrying"): 1,
        key(state_type="SCHEDULED", state_name="Late"): 1,
        key(state_type="PAUSED", state_name="Suspended", work_queue_name="other"): 1,
    }


@responses.activate
def test_each_non_terminal_state_type_is_queried_and_scheduled_is_bounded():
    _register([])

    _poller().poll()

    bodies = [
        json.loads(c.request.body)
        for c in responses.calls
        if c.request.url == f"{URL}/flow_runs/filter"
    ]
    by_state = {b["flow_runs"]["state"]["type"]["any_"][0]: b for b in bodies}
    assert set(by_state) == {"SCHEDULED", "PENDING", "RUNNING", "PAUSED", "CANCELLING"}
    assert by_state["SCHEDULED"]["flow_runs"]["expected_start_time"] == {
        "before_": "2026-11-17T12:00:00.000000Z"
    }
    assert "expected_start_time" not in by_state["RUNNING"]["flow_runs"]
    assert all(b["sort"] == "ID_DESC" for b in bodies)


@responses.activate
def test_ongoing_run_time_has_work_queue_and_times_unstarted_runs_from_expected_start():
    _register(
        [
            _run("r1", "RUNNING", "Running", start_time="2026-11-17T11:00:00+00:00"),
            _run(
                "r2",
                "SCHEDULED",
                "Late",
                start_time=None,
                expected_start_time="2026-11-17T11:50:00+00:00",
            ),
            _run("r3", "PAUSED", "Paused", start_time="2026-11-17T10:00:00+00:00"),
        ]
    )

    samples = _samples(_poller().poll(), "prefect_flow_runs_ongoing_run_time")

    def key(run_id, state_name):
        return tuple(
            sorted(
                {
                    "deployment_name": "dep-one",
                    "flow_name": "flow-one",
                    "state_name": state_name,
                    "flow_run_id": run_id,
                    "work_queue_name": "default",
                }.items()
            )
        )

    assert samples == {key("r1", "Running"): 3600.0, key("r2", "Late"): 600.0}


@responses.activate
def test_naive_and_future_start_times_do_not_break_the_poll():
    _register(
        [
            _run("r1", "RUNNING", "Running", start_time="2026-11-17T11:59:00"),
            _run("r2", "RUNNING", "Running", start_time="2026-11-17T12:05:00+00:00"),
            _run("r3", "RUNNING", "Running", start_time="not-a-time"),
        ]
    )

    samples = _samples(_poller().poll(), "prefect_flow_runs_ongoing_run_time")

    values = {dict(k)["flow_run_id"]: v for k, v in samples.items()}
    assert values == {"r1": 60.0, "r2": 0.0}


@responses.activate
def test_flow_run_name_label_is_added_to_both_gauges():
    _register([_run("r1", "RUNNING", "Running", start_time="2026-11-17T11:00:00Z")])

    result = _poller(flow_run_name=True).poll()

    for name in ("prefect_flow_runs_current", "prefect_flow_runs_ongoing_run_time"):
        [labels] = [dict(k) for k in _samples(result, name)]
        assert labels["flow_run_name"] == "name-r1"


@responses.activate
def test_names_missing_from_the_inventory_are_looked_up_by_id():
    _register([_run("r1", "PENDING", "Pending", deployment_id="d9", flow_id="f9")])
    responses.add(
        responses.POST,
        f"{URL}/deployments/filter",
        json=[{"id": "d9", "name": "dep-nine"}],
    )
    responses.add(
        responses.POST, f"{URL}/flows/filter", json=[{"id": "f9", "name": "flow-nine"}]
    )

    result = _poller(names=InventoryNames()).poll()

    [labels] = [dict(k) for k in _samples(result, "prefect_flow_runs_current")]
    assert labels["deployment_name"] == "dep-nine"
    assert labels["flow_name"] == "flow-nine"


@responses.activate
def test_failed_listing_makes_the_poll_incomplete():
    responses.add(responses.POST, f"{URL}/flow_runs/filter-minimal", status=404)
    responses.add(responses.POST, f"{URL}/flow_runs/filter", status=500)

    assert _poller().poll().complete is False
