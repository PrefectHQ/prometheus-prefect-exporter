"""Tests for PrefectFlowRuns.get_flow_runs_info().

Covers the fix for issue #113: a single unfiltered flow-runs query is capped by
the page/pagination limit and sorted by start_time, so a high-volume state
(COMPLETED) can crowd FAILED/CRASHED runs out of the returned window. The method
now queries each state type separately and merges the results, so no state is
silently truncated.
"""

import json
import logging

import responses

from metrics.flow_runs import PrefectFlowRuns

URL = "http://prefect.test/api"


def _make(enable_pagination=False, pagination_limit=200):
    return PrefectFlowRuns(
        url=URL,
        headers={"accept": "application/json"},
        max_retries=3,
        offset_minutes=3,
        logger=logging.getLogger("test"),
        enable_pagination=enable_pagination,
        pagination_limit=pagination_limit,
    )


def _register_by_state(runs_by_state):
    """Route flow_runs/filter by the single state type in the request body.

    Mirrors how the real API would answer a state-filtered query: each query
    sees only its own state's runs, so it is bounded by that state's volume and
    never truncated by the more numerous COMPLETED runs.
    """

    def callback(request):
        body = json.loads(request.body)
        state_filter = body["flow_runs"]["state"]["type"]["any_"]
        # get_flow_runs_info queries one state type at a time.
        state_type = state_filter[0]
        limit = body.get("limit")
        offset = body.get("offset", 0)
        runs = runs_by_state.get(state_type, [])
        page = runs[offset : offset + limit] if limit is not None else runs
        return (200, {}, json.dumps(page))

    responses.add_callback(
        responses.POST,
        f"{URL}/flow_runs/filter",
        callback=callback,
        content_type="application/json",
    )


def _run(run_id, state_type):
    return {
        "id": run_id,
        "deployment_id": "dep-1",
        "flow_id": "flow-1",
        "state_name": state_type.capitalize(),
        "start_time": "2026-06-01T10:00:00+00:00",
    }


@responses.activate
def test_failed_runs_not_crowded_out_by_completed():
    """FAILED/CRASHED runs are returned even when COMPLETED alone exceeds the limit.

    With a single unfiltered query (limit 200) and 200 COMPLETED runs sorted
    first, the FAILED/CRASHED runs would never appear. Per-state querying
    surfaces them regardless.
    """
    runs_by_state = {
        "COMPLETED": [_run(f"done-{i}", "COMPLETED") for i in range(200)],
        "FAILED": [_run("fail-1", "FAILED"), _run("fail-2", "FAILED")],
        "CRASHED": [_run("crash-1", "CRASHED")],
    }
    _register_by_state(runs_by_state)

    result = _make(enable_pagination=False, pagination_limit=200).get_flow_runs_info()

    ids = {r["id"] for r in result}
    assert "fail-1" in ids
    assert "fail-2" in ids
    assert "crash-1" in ids
    # All completed runs are still present too.
    assert len([r for r in result if r["id"].startswith("done-")]) == 200


@responses.activate
def test_queries_every_state_type():
    """One query is issued per state type, covering all of them."""
    _register_by_state({})
    _make().get_flow_runs_info()

    queried_states = []
    for call in responses.calls:
        body = json.loads(call.request.body)
        queried_states.extend(body["flow_runs"]["state"]["type"]["any_"])

    assert set(queried_states) == set(PrefectFlowRuns.STATE_TYPES)


@responses.activate
def test_results_deduplicated_by_id():
    """A run id observed in two state queries is counted once."""
    shared = _run("shared", "RUNNING")
    runs_by_state = {
        "RUNNING": [shared],
        # Same id reappears under COMPLETED (e.g. it transitioned mid-scrape).
        "COMPLETED": [dict(shared, state_name="Completed")],
    }
    _register_by_state(runs_by_state)

    result = _make().get_flow_runs_info()

    assert [r["id"] for r in result].count("shared") == 1


@responses.activate
def test_carries_start_time_filter():
    """Each per-state query still constrains by the start_time window."""
    _register_by_state({})
    _make().get_flow_runs_info()

    for call in responses.calls:
        body = json.loads(call.request.body)
        assert "after_" in body["flow_runs"]["start_time"]


@responses.activate
def test_pagination_applies_per_state():
    """With pagination on, each state is fully paged, not capped at one page."""
    runs_by_state = {
        "FAILED": [_run(f"fail-{i}", "FAILED") for i in range(5)],
    }
    _register_by_state(runs_by_state)

    result = _make(enable_pagination=True, pagination_limit=2).get_flow_runs_info()

    failed_ids = {r["id"] for r in result if r["id"].startswith("fail-")}
    assert len(failed_ids) == 5
