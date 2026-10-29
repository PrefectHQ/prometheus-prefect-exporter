import logging

from metrics.api_metric import PrefectApiMetric
from metrics.flow_runs import PrefectFlowRuns
from metrics.metrics import PrefectMetrics

NAMES = {"d1": "dep-one", "f1": "flow-one", "d2": "dep-two", "f2": "flow-two"}


def test_names_and_totals_survive_an_empty_listing(monkeypatch):
    stubs = [
        # Every listing comes back empty, as when the server fails the first page.
        (PrefectApiMetric, "_get_with_pagination", lambda self, base_data=None: []),
        (
            PrefectApiMetric,
            "get_by_ids",
            lambda self, ids: [{"id": i, "name": NAMES[i]} for i in ids if i in NAMES],
        ),
        (
            PrefectApiMetric,
            "get_count",
            lambda self: {"deployments": 12345, "flows": 678}[self.uri],
        ),
        (
            PrefectFlowRuns,
            "get_flow_runs_info",
            lambda self: [{"deployment_id": "d1", "flow_id": "f1"}],
        ),
        (
            PrefectFlowRuns,
            "get_failed_flow_runs_info",
            lambda self, limit: {("d2", "f2", "Failed"): ["run-2"]},
        ),
    ]
    for cls, name, stub in stubs:
        monkeypatch.setattr(cls, name, stub)
    metrics = PrefectMetrics(
        url="http://prefect.test/api",
        headers={},
        offset_minutes=3,
        failed_runs_offset_minutes=60,
        failed_runs_limit=10,
        max_retries=3,
        client_id="test-client-id",
        csrf_enabled=False,
        logger=logging.getLogger("test"),
        enable_pagination=False,
        pagination_limit=200,
    )

    families = {family.name: family for family in metrics._collect_metrics()}

    assert families["prefect_deployments_total"].samples[0].value == 12345
    assert families["prefect_flows_total"].samples[0].value == 678
    [run] = families["prefect_info_flow_runs"].samples
    assert run.labels["deployment_name"] == "dep-one"
    assert run.labels["flow_name"] == "flow-one"
    [failed] = families["prefect_deployment_failed_flow_runs"].samples
    assert failed.labels["deployment_name"] == "dep-two"
    assert failed.labels["flow_name"] == "flow-two"
