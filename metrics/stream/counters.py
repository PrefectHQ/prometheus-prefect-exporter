from prometheus_client import REGISTRY, CollectorRegistry, Counter, Histogram

from metrics.stream.classifier import Classification, TerminalLabels

TERMINAL_LABELS = (
    "deployment_name",
    "flow_name",
    "work_pool_name",
    "work_queue_name",
    "state_type",
    "state_name",
)

# The (state type, state name) pairs whose counter series exist at zero for
# every deployment and every flow without one, so increase() includes their
# first count. Custom state names start at their first count instead.
PRECREATED_STATES = (
    ("COMPLETED", "Completed"),
    ("COMPLETED", "Cached"),
    ("FAILED", "Failed"),
    ("FAILED", "TimedOut"),
    ("CRASHED", "Crashed"),
    ("CANCELLED", "Cancelled"),
)

DURATION_BUCKETS = (1, 5, 15, 30, 60, 300, 900, 1800, 3600, 7200, 21600, 43200, 86400)


class FlowRunStreamMetrics:
    """The flow-run metrics fed by the event stream."""

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.terminal = Counter(
            "prefect_flow_runs_terminal",
            "Terminal states entered by flow run attempts, each counted once per "
            "attempt and state type",
            TERMINAL_LABELS,
            registry=registry,
        )
        self.duration = Histogram(
            "prefect_flow_run_duration_seconds",
            "Time flow run attempts spent running before reaching a terminal state",
            ("deployment_name", "flow_name", "state_type"),
            buckets=DURATION_BUCKETS,
            registry=registry,
        )

    def record(self, classification: Classification) -> None:
        """Count a terminal state the classifier counted, and its duration."""
        if classification.outcome != "counted":
            return
        labels = classification.labels
        self.terminal.labels(*_terminal_values(labels)).inc()
        if classification.duration_seconds is not None:
            self.duration.labels(
                labels.deployment_name, labels.flow_name, labels.state_type
            ).observe(classification.duration_seconds)

    def precreate(self, deployments: list, flows: list) -> None:
        """
        Create the terminal counter's series at zero for each deployment, with
        its flow, work pool and default work queue, and for each flow that has
        no deployment. Existing series keep their values.
        """
        flow_names = {f.get("id"): f.get("name") for f in flows if f.get("name")}
        flows_with_deployments = set()
        for deployment in deployments:
            flow_id = deployment.get("flow_id")
            flows_with_deployments.add(flow_id)
            # The run events carry the flow's name; without it the series
            # would not match them.
            if flow_id not in flow_names or not deployment.get("name"):
                continue
            self._precreate_series(
                deployment["name"],
                flow_names[flow_id],
                deployment.get("work_pool_name") or "",
                deployment.get("work_queue_name") or "",
            )
        for flow_id, flow_name in flow_names.items():
            if flow_id not in flows_with_deployments:
                self._precreate_series("", flow_name, "", "")

    def _precreate_series(self, deployment, flow, work_pool, work_queue) -> None:
        for state_type, state_name in PRECREATED_STATES:
            self.terminal.labels(
                deployment, flow, work_pool, work_queue, state_type, state_name
            )


def _terminal_values(labels: TerminalLabels) -> tuple:
    return (
        labels.deployment_name,
        labels.flow_name,
        labels.work_pool_name,
        labels.work_queue_name,
        labels.state_type,
        labels.state_name,
    )
