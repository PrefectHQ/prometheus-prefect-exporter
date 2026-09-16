import logging

import pytest

from metrics.metrics import PrefectMetrics


def _make():
    return PrefectMetrics(
        url="http://prefect.test/api",
        headers={"accept": "application/json"},
        offset_minutes=3,
        failed_runs_offset_minutes=0,
        failed_runs_limit=10,
        max_retries=3,
        client_id="test-client-id",
        csrf_enabled=False,
        logger=logging.getLogger("test"),
        enable_pagination=False,
        pagination_limit=200,
    )


def _stub_api(monkeypatch, deployments, flows, all_flow_runs):
    monkeypatch.setattr(
        "metrics.metrics.PrefectDeployments.get_deployments_info",
        lambda self: deployments,
    )
    monkeypatch.setattr(
        "metrics.metrics.PrefectFlows.get_flows_info",
        lambda self: flows,
    )
    monkeypatch.setattr(
        "metrics.metrics.PrefectFlowRuns.get_flow_runs_info",
        lambda self: [],
    )
    monkeypatch.setattr(
        "metrics.metrics.PrefectFlowRuns.get_all_flow_runs_info",
        lambda self: all_flow_runs,
    )
    monkeypatch.setattr(
        "metrics.metrics.PrefectFlowRuns.get_ongoing_flow_runs_info",
        lambda self: [],
    )
    monkeypatch.setattr(
        "metrics.metrics.PrefectWorkPools.get_work_pools_info",
        lambda self: [],
    )
    monkeypatch.setattr(
        "metrics.metrics.PrefectWorkQueues.get_work_queues_info",
        lambda self: [],
    )


def _total_run_time_family(metrics):
    return next(
        family
        for family in metrics._collect_metrics()
        if family.name == "prefect_flow_runs_total_run_time"
    )


def test_total_run_time_includes_deployment_name(monkeypatch):
    _stub_api(
        monkeypatch,
        deployments=[{"id": "deployment-1", "name": "my-deployment"}],
        flows=[{"id": "flow-1", "name": "my-flow"}],
        all_flow_runs=[
            {
                "deployment_id": "deployment-1",
                "flow_id": "flow-1",
                "total_run_time": 42,
            }
        ],
    )

    family = _total_run_time_family(_make())

    assert len(family.samples) == 1
    sample = family.samples[0]
    assert sample.labels == {
        "flow_name": "my-flow",
        "deployment_name": "my-deployment",
    }
    assert sample.value == 42


@pytest.mark.parametrize("deployment_id", [None, "missing-deployment"])
def test_total_run_time_uses_null_for_unresolved_deployment(monkeypatch, deployment_id):
    _stub_api(
        monkeypatch,
        deployments=[],
        flows=[{"id": "flow-1", "name": "my-flow"}],
        all_flow_runs=[
            {
                "deployment_id": deployment_id,
                "flow_id": "flow-1",
                "total_run_time": 42,
            }
        ],
    )

    family = _total_run_time_family(_make())

    assert family.samples[0].labels["deployment_name"] == "null"
