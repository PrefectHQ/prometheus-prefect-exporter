import json
import logging
from datetime import datetime, timezone

import pytest
import responses
from prometheus_client import CollectorRegistry

from metrics.health import ExporterHealth
from metrics.inventory import InventoryNames, InventoryPoller

URL = "http://prefect.test/api"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

DEPLOYMENTS = [
    {
        "id": "d1",
        "name": "dep-one",
        "flow_id": "f1",
        "paused": False,
        "tags": ["b", "a"],
        "work_pool_name": "pool",
        "work_queue_name": "default",
        "status": "READY",
        "path": ".",
    }
]
FLOWS = [{"id": "f1", "name": "flow-one"}, {"id": "f2", "name": "flow-two"}]
QUEUE = {
    "id": "q1",
    "name": "default",
    "is_paused": False,
    "priority": 1,
    "type": None,
    "work_pool_name": "pool",
    "status": "READY",
}
QUEUE_STATUS = {
    "healthy": True,
    "late_runs_count": 4,
    "health_check_policy": {
        "maximum_late_runs": 0,
        "maximum_seconds_since_last_polled": 60,
    },
}


def _listing(url, items, lookup=()):
    """
    Serve `items` on the first page and nothing after it, and answer id
    lookups from `items` plus `lookup`.
    """

    def callback(request):
        body = json.loads(request.body)
        if "offset" not in body:
            [resource_filter] = [v for k, v in body.items() if k != "limit"]
            ids = resource_filter["id"]["any_"]
            found = [i for i in [*items, *lookup] if i["id"] in ids]
            return (200, {}, json.dumps(found))
        return (200, {}, json.dumps(items if body["offset"] == 0 else []))

    responses.add_callback(responses.POST, url, callback=callback)


def _register(failed_runs=(), deployment_lookup=(), flow_lookup=()):
    _listing(f"{URL}/deployments/filter", DEPLOYMENTS, deployment_lookup)
    _listing(f"{URL}/flows/filter", FLOWS, flow_lookup)
    _listing(f"{URL}/work_pools/filter", [{"name": "pool", "type": "process"}])
    _listing(f"{URL}/work_queues/filter", [QUEUE])
    responses.add(responses.GET, f"{URL}/work_queues/q1/status", json=QUEUE_STATUS)
    responses.add(responses.POST, f"{URL}/deployments/count", json=1)
    responses.add(responses.POST, f"{URL}/flows/count", json=2)
    responses.add(responses.POST, f"{URL}/flow_runs/filter-minimal", status=404)
    _listing(f"{URL}/flow_runs/filter", list(failed_runs))


def _poller(failed_runs_offset_minutes=60, on_inventory=None):
    return InventoryPoller(
        dict(
            url=URL,
            headers={},
            max_retries=1,
            logger=logging.getLogger("test"),
            enable_pagination=True,
            pagination_limit=200,
            timeout=7,
            health=ExporterHealth(CollectorRegistry()),
        ),
        failed_runs_offset_minutes=failed_runs_offset_minutes,
        failed_runs_limit=10,
        on_inventory=on_inventory,
        now=lambda: NOW,
    )


def _families(result):
    return {f.name: f for f in result.families}


@responses.activate
def test_inventory_metrics_keep_their_names_and_labels():
    _register()

    result = _poller().poll()

    assert result.complete
    families = _families(result)
    assert set(families) == {
        "prefect_deployments_total",
        "prefect_info_deployment",
        "prefect_flows_total",
        "prefect_info_flows",
        "prefect_deployment_failed_flow_runs",
        "prefect_work_pools_total",
        "prefect_info_work_pools",
        "prefect_work_queues_total",
        "prefect_info_work_queues",
        "prefect_work_queues_late_runs_count",
    }
    [deployment] = families["prefect_info_deployment"].samples
    assert deployment.labels == {
        "flow_name": "flow-one",
        "is_schedule_active": "True",
        "deployment_name": "dep-one",
        "path": ".",
        "paused": "False",
        "work_pool_name": "pool",
        "work_queue_name": "default",
        "status": "READY",
        "tags": "a,b",
    }
    assert families["prefect_flows_total"].samples[0].value == 2
    [late] = families["prefect_work_queues_late_runs_count"].samples
    assert late.value == 4
    assert late.labels["healthy"] == "True"


@responses.activate
def test_failed_runs_are_named_and_limited_per_deployment():
    _register(
        [
            {
                "id": "r1",
                "deployment_id": "d1",
                "flow_id": "f1",
                "state_name": "Failed",
            },
            {
                "id": "r2",
                "deployment_id": "d7",
                "flow_id": "f7",
                "state_name": "Crashed",
            },
        ],
        deployment_lookup=[{"id": "d7", "name": "dep-seven"}],
        flow_lookup=[{"id": "f7", "name": "flow-seven"}],
    )

    families = _families(_poller().poll())

    samples = {
        s.labels["last_failed_run_id"]: s.labels
        for s in families["prefect_deployment_failed_flow_runs"].samples
    }
    assert samples["r1"]["deployment_name"] == "dep-one"
    assert samples["r2"] == {
        "deployment_name": "dep-seven",
        "flow_name": "flow-seven",
        "last_failed_run_id": "r2",
        "state_name": "Crashed",
    }
    [failed_query] = [
        json.loads(c.request.body)
        for c in responses.calls
        if c.request.url == f"{URL}/flow_runs/filter"
        and json.loads(c.request.body)["offset"] == 0
    ]
    assert failed_query["sort"] == "START_TIME_DESC"
    assert failed_query["flow_runs"]["start_time"] == {
        "after_": "2026-11-17T11:00:00.000000Z"
    }


@responses.activate
def test_failed_runs_window_of_zero_sends_no_flow_run_query():
    _register()

    families = _families(_poller(failed_runs_offset_minutes=0).poll())

    assert families["prefect_deployment_failed_flow_runs"].samples == []
    assert not any("flow_runs" in c.request.url for c in responses.calls)


@responses.activate
def test_names_and_inventory_are_published_to_the_hook():
    _register()
    seen = []
    poller = _poller(on_inventory=lambda d, f: seen.append((d, f)))

    poller.poll()

    assert poller.names == InventoryNames(
        {"d1": "dep-one"}, {"f1": "flow-one", "f2": "flow-two"}
    )
    assert seen == [(DEPLOYMENTS, FLOWS)]


@responses.activate
@pytest.mark.parametrize("failing", ["/deployments/count", "/work_queues/q1/status"])
def test_any_failed_request_makes_the_poll_incomplete(failing):
    method = responses.GET if "status" in failing else responses.POST
    responses.add(method, f"{URL}{failing}", status=500)
    _register()

    result = _poller().poll()

    assert result.complete is False
    families = _families(result)
    if failing == "/deployments/count":
        assert families["prefect_deployments_total"].samples == []
    else:
        assert families["prefect_work_queues_late_runs_count"].samples == []


@responses.activate
def test_every_request_carries_the_configured_timeout():
    _register()

    _poller().poll()

    assert {call.request.req_kwargs["timeout"] for call in responses.calls} == {7}
