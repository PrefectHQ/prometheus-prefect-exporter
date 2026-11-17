from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from prometheus_client.core import GaugeMetricFamily

from metrics.deployments import PrefectDeployments
from metrics.flow_runs import PrefectFlowRuns
from metrics.flows import PrefectFlows
from metrics.poller import PollResult
from metrics.work_pools import PrefectWorkPools
from metrics.work_queues import PrefectWorkQueues


@dataclass(frozen=True)
class InventoryNames:
    """Deployment and flow names by id, from the latest inventory poll."""

    deployments_by_id: dict = field(default_factory=dict)
    flows_by_id: dict = field(default_factory=dict)


class InventoryPoller:
    """
    Builds the inventory metrics (deployments, flows, work pools, work queues)
    and `prefect_deployment_failed_flow_runs`.
    """

    def __init__(
        self,
        api_kwargs: dict,
        failed_runs_offset_minutes: int,
        failed_runs_limit: int,
        on_inventory: Optional[Callable[[list, list], None]] = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """
        Args:
            api_kwargs (dict): Keyword arguments for each API client.
            failed_runs_offset_minutes (int): The window of the failed-runs
                metric; 0 disables it.
            failed_runs_limit (int): Failed runs reported per deployment.
            on_inventory (callable, optional): Called with the deployments and
                flows of every poll.
            now (callable): The current time, for tests.
        """
        self.deployments = PrefectDeployments(**api_kwargs)
        self.flows = PrefectFlows(**api_kwargs)
        self.flow_runs = PrefectFlowRuns(**api_kwargs)
        self.work_pools = PrefectWorkPools(**api_kwargs)
        self.work_queues = PrefectWorkQueues(**api_kwargs)
        self.failed_runs_offset_minutes = failed_runs_offset_minutes
        self.failed_runs_limit = failed_runs_limit
        self.on_inventory = on_inventory
        self.now = now
        self.names = InventoryNames()

    def _apis(self):
        return (
            self.deployments,
            self.flows,
            self.flow_runs,
            self.work_pools,
            self.work_queues,
        )

    def poll(self) -> PollResult:
        failures_before = sum(api.failed_requests for api in self._apis())

        deployments = self.deployments.get_deployments_info()
        flows = self.flows.get_flows_info()
        work_pools = self.work_pools.get_work_pools_info()
        work_queues = self.work_queues.get_work_queues_info()
        if self.failed_runs_offset_minutes == 0:
            failed_flow_runs, failed_complete = {}, True
        else:
            (
                failed_flow_runs,
                failed_complete,
            ) = self.flow_runs.get_failed_flow_runs_info(
                limit=self.failed_runs_limit,
                offset_minutes=self.failed_runs_offset_minutes,
                now=self.now(),
            )

        deployments_by_id = {d["id"]: d["name"] for d in deployments if d.get("id")}
        flows_by_id = {f["id"]: f["name"] for f in flows if f.get("id")}
        self.names = InventoryNames(dict(deployments_by_id), dict(flows_by_id))

        # A failed page leaves the listings incomplete, so fetch missing names by ID.
        deployment_ids = {deployment_id for deployment_id, _, _ in failed_flow_runs}
        flow_ids = {flow_id for _, flow_id, _ in failed_flow_runs}
        for d in self.deployments.get_by_ids(deployment_ids - deployments_by_id.keys()):
            deployments_by_id[d["id"]] = d["name"]
        for f in self.flows.get_by_ids(flow_ids - flows_by_id.keys()):
            flows_by_id[f["id"]] = f["name"]

        if self.on_inventory is not None:
            self.on_inventory(deployments, flows)

        families = (
            *self._deployment_families(deployments, flows),
            *self._flow_families(flows),
            self._failed_runs_family(failed_flow_runs, deployments_by_id, flows_by_id),
            *self._work_pool_families(work_pools),
            *self._work_queue_families(work_queues),
        )
        complete = (
            all(
                listing.complete
                for listing in (deployments, flows, work_pools, work_queues)
            )
            and failed_complete
            and sum(api.failed_requests for api in self._apis()) == failures_before
        )
        return PollResult(families=families, complete=complete)

    def _deployment_families(self, deployments, flows):
        prefect_deployments = GaugeMetricFamily(
            "prefect_deployments_total", "Prefect total deployments", labels=[]
        )
        deployments_count = self.deployments.get_count()
        if deployments_count is not None:
            prefect_deployments.add_metric([], deployments_count)

        prefect_info_deployments = GaugeMetricFamily(
            "prefect_info_deployment",
            "Prefect deployment info",
            labels=[
                "flow_name",
                "is_schedule_active",
                "deployment_name",
                "path",
                "paused",
                "work_pool_name",
                "work_queue_name",
                "status",
                "tags",
            ],
        )

        flow_names = {f.get("id"): f.get("name") for f in flows}
        for deployment in deployments:
            flow_name = flow_names.get(deployment.get("flow_id")) or "null"

            # The "is_schedule_active" field is deprecated, and always returns
            # "null". For backward compatibility, we will populate the value of
            # this label with the "paused" field.
            is_schedule_active = deployment.get("paused", "null")
            if is_schedule_active != "null":
                # Negate the value we get from "paused" because "is_schedule_active"
                # is the opposite of "paused".
                is_schedule_active = not is_schedule_active

            tags = deployment.get("tags", "null")
            if tags != "null":
                tags = ",".join(sorted(tags))

            prefect_info_deployments.add_metric(
                [
                    str(flow_name),
                    str(is_schedule_active),
                    str(deployment.get("name", "null")),
                    str(deployment.get("path", "null")),
                    str(deployment.get("paused", "null")),
                    str(deployment.get("work_pool_name", "null")),
                    str(deployment.get("work_queue_name", "null")),
                    str(deployment.get("status", "null")),
                    tags,
                ],
                1,
            )

        return prefect_deployments, prefect_info_deployments

    def _flow_families(self, flows):
        prefect_flows = GaugeMetricFamily(
            "prefect_flows_total", "Prefect total flows", labels=[]
        )
        flows_count = self.flows.get_count()
        if flows_count is not None:
            prefect_flows.add_metric([], flows_count)

        prefect_info_flows = GaugeMetricFamily(
            "prefect_info_flows",
            "Prefect flow info",
            labels=["flow_name"],
        )
        for flow in flows:
            prefect_info_flows.add_metric([str(flow.get("name", "null"))], 1)

        return prefect_flows, prefect_info_flows

    def _failed_runs_family(self, failed_flow_runs, deployments_by_id, flows_by_id):
        prefect_deployment_failed_flow_runs = GaugeMetricFamily(
            "prefect_deployment_failed_flow_runs",
            "Last failed or crashed flow run ID per deployment within the FAILED_RUNS_OFFSET_MINUTES window",
            labels=["deployment_name", "flow_name", "last_failed_run_id", "state_name"],
        )
        for (deployment_id, flow_id, state_name), run_ids in failed_flow_runs.items():
            deployment_name = deployments_by_id.get(deployment_id, "null")
            flow_name = flows_by_id.get(flow_id, "null")
            for run_id in run_ids:
                prefect_deployment_failed_flow_runs.add_metric(
                    [deployment_name, flow_name, run_id, str(state_name)], 1
                )
        return prefect_deployment_failed_flow_runs

    def _work_pool_families(self, work_pools):
        prefect_work_pools = GaugeMetricFamily(
            "prefect_work_pools_total", "Prefect total work pools", labels=[]
        )
        prefect_work_pools.add_metric([], len(work_pools))

        prefect_info_work_pools = GaugeMetricFamily(
            "prefect_info_work_pools",
            "Prefect work pools info",
            labels=["is_paused", "work_pool_name", "type", "status"],
        )
        for work_pool in work_pools:
            state = 0 if work_pool.get("is_paused") else 1
            prefect_info_work_pools.add_metric(
                [
                    str(work_pool.get("is_paused", "null")),
                    str(work_pool.get("name", "null")),
                    str(work_pool.get("type", "null")),
                    str(work_pool.get("status", "null")),
                ],
                state,
            )

        return prefect_work_pools, prefect_info_work_pools

    def _work_queue_families(self, work_queues):
        prefect_work_queues = GaugeMetricFamily(
            "prefect_work_queues_total", "Prefect total work queues", labels=[]
        )
        prefect_work_queues.add_metric([], len(work_queues))

        queue_labels = [
            "is_paused",
            "work_queue_name",
            "priority",
            "type",
            "work_pool_name",
            "status",
            "healthy",
            "health_check_policy_maximum_late_runs",
            "health_check_policy_maximum_seconds_since_last_polled",
        ]
        prefect_info_work_queues = GaugeMetricFamily(
            "prefect_info_work_queues",
            "Prefect work queues info",
            labels=queue_labels,
        )
        prefect_work_queues_late_runs_count = GaugeMetricFamily(
            "prefect_work_queues_late_runs_count",
            "Prefect work queues late runs count",
            labels=queue_labels,
        )

        for work_queue in work_queues:
            state = 0 if work_queue.get("is_paused") else 1
            status_info = work_queue.get("status_info", {})
            health_check_policy = status_info.get("health_check_policy", {})
            label_values = [
                str(work_queue.get("is_paused", "null")),
                str(work_queue.get("name", "null")),
                str(work_queue.get("priority", "null")),
                str(work_queue.get("type", "null")),
                str(work_queue.get("work_pool_name", "null")),
                str(work_queue.get("status", "null")),
                str(status_info.get("healthy", "null")),
                str(health_check_policy.get("maximum_late_runs", "null")),
                str(
                    health_check_policy.get("maximum_seconds_since_last_polled", "null")
                ),
            ]
            prefect_info_work_queues.add_metric(label_values, state)
            late_runs = status_info.get("late_runs_count")
            if late_runs is not None:
                prefect_work_queues_late_runs_count.add_metric(label_values, late_runs)

        return (
            prefect_work_queues,
            prefect_info_work_queues,
            prefect_work_queues_late_runs_count,
        )
