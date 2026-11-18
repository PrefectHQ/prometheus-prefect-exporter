import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Optional

from prometheus_client.core import GaugeMetricFamily

from metrics.deployments import PrefectDeployments
from metrics.flow_runs import PrefectFlowRuns
from metrics.flows import PrefectFlows
from metrics.inventory import InventoryNames
from metrics.poller import PollResult

# State types whose runs have a run time on prefect_flow_runs_ongoing_run_time.
ONGOING_STATE_TYPES = ("RUNNING", "PENDING", "SCHEDULED")


def _parse_timestamp(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    # The API may omit the offset; its timestamps are UTC.
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


class RunGaugePoller:
    """
    Builds the gauges of runs that have not ended: `prefect_flow_runs_current`
    and `prefect_flow_runs_ongoing_run_time`.
    """

    def __init__(
        self,
        api_kwargs: dict,
        inventory_names: Callable[[], InventoryNames],
        enable_flow_run_name_label: bool,
        logger: logging.Logger,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """
        Args:
            api_kwargs (dict): Keyword arguments for each API client.
            inventory_names (callable): Returns the latest inventory names.
                Names it does not have are looked up by id.
            enable_flow_run_name_label (bool): Adds `flow_run_name` to both gauges.
            logger (logging.Logger): The logger.
            now (callable): The current time, for tests.
        """
        self.deployments = PrefectDeployments(**api_kwargs)
        self.flows = PrefectFlows(**api_kwargs)
        self.flow_runs = PrefectFlowRuns(**api_kwargs)
        self.inventory_names = inventory_names
        self.enable_flow_run_name_label = enable_flow_run_name_label
        self.logger = logger
        self.now = now

    def _apis(self):
        return (self.deployments, self.flows, self.flow_runs)

    def poll(self) -> PollResult:
        failures_before = sum(api.failed_requests for api in self._apis())
        now = self.now()
        runs = self.flow_runs.get_current_flow_runs(now)

        names = self.inventory_names()
        deployments_by_id = dict(names.deployments_by_id)
        flows_by_id = dict(names.flows_by_id)
        deployment_ids = {r.get("deployment_id") for r in runs}
        flow_ids = {r.get("flow_id") for r in runs}
        for d in self.deployments.get_by_ids(deployment_ids - deployments_by_id.keys()):
            deployments_by_id[d["id"]] = d["name"]
        for f in self.flows.get_by_ids(flow_ids - flows_by_id.keys()):
            flows_by_id[f["id"]] = f["name"]

        families = (
            self._current_family(runs, deployments_by_id, flows_by_id),
            self._ongoing_family(runs, deployments_by_id, flows_by_id, now),
        )
        complete = (
            runs.complete
            and sum(api.failed_requests for api in self._apis()) == failures_before
        )
        return PollResult(families=families, complete=complete)

    def _current_family(self, runs, deployments_by_id, flows_by_id):
        labels = [
            "deployment_name",
            "flow_name",
            "work_queue_name",
            "state_type",
            "state_name",
        ]
        if self.enable_flow_run_name_label:
            labels.append("flow_run_name")
        family = GaugeMetricFamily(
            "prefect_flow_runs_current",
            "Prefect flow runs in each non-terminal state. Scheduled runs count "
            "once their expected start time has passed.",
            labels=labels,
        )

        counts = defaultdict(int)
        for flow_run in runs:
            # Empty, not "null", matches the labels of prefect_flow_runs_terminal_total.
            key = (
                deployments_by_id.get(flow_run.get("deployment_id"), ""),
                flows_by_id.get(flow_run.get("flow_id"), ""),
                flow_run.get("work_queue_name") or "",
                flow_run.get("state_type") or "",
                flow_run.get("state_name") or "",
            )
            if self.enable_flow_run_name_label:
                key += (flow_run.get("name") or "",)
            counts[key] += 1
        for key, count in counts.items():
            family.add_metric(list(key), count)
        return family

    def _ongoing_family(self, runs, deployments_by_id, flows_by_id, now):
        # flow_run_id keeps each ongoing run a distinct timeseries. Without it,
        # multiple runs of the same flow/deployment/state collapse to identical
        # label tuples and Prometheus rejects the scrape as duplicate samples.
        labels = [
            "deployment_name",
            "flow_name",
            "state_name",
            "flow_run_id",
            "work_queue_name",
        ]
        if self.enable_flow_run_name_label:
            labels.append("flow_run_name")
        family = GaugeMetricFamily(
            "prefect_flow_runs_ongoing_run_time",
            "Prefect flow runs ongoing run time in seconds",
            labels=labels,
        )

        for flow_run in runs:
            if flow_run.get("state_type") not in ONGOING_STATE_TYPES:
                continue
            # A run that has not started (Scheduled, Late, Pending) is timed
            # from its expected start.
            raw_start = flow_run.get("start_time") or flow_run.get(
                "expected_start_time"
            )
            start = _parse_timestamp(raw_start)
            if start is None:
                if raw_start:
                    self.logger.warning(
                        "Skipping ongoing flow run %s: unparseable start time %r",
                        flow_run.get("id"),
                        raw_start,
                    )
                continue

            label_values = [
                str(deployments_by_id.get(flow_run.get("deployment_id"), "null")),
                str(flows_by_id.get(flow_run.get("flow_id"), "null")),
                str(flow_run.get("state_name", "null")),
                str(flow_run.get("id", "null")),
                str(flow_run.get("work_queue_name") or "null"),
            ]
            if self.enable_flow_run_name_label:
                label_values.append(str(flow_run.get("name", "null")))
            # Clamped so a clock skew never reports a negative run time.
            family.add_metric(label_values, max(0.0, (now - start).total_seconds()))
        return family
