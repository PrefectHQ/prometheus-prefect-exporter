from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram

POLLERS = ("inventory", "runs")


class ExporterHealth:
    """The `prefect_exporter_*` metrics that report the exporter's own health."""

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.api_errors = Counter(
            "prefect_exporter_api_errors",
            "Failed Prefect API requests, by endpoint and HTTP status",
            ["endpoint", "status"],
            registry=registry,
        )
        self.poll_truncated = Counter(
            "prefect_exporter_poll_truncated",
            "Listings whose pagination stopped before the last page, by endpoint",
            ["endpoint"],
            registry=registry,
        )
        self.poll_success = Gauge(
            "prefect_exporter_poll_success",
            "1 if the last poll of this poller succeeded, 0 otherwise",
            ["poller"],
            registry=registry,
        )
        self.poll_duration = Histogram(
            "prefect_exporter_poll_duration_seconds",
            "Duration of each poll",
            ["poller"],
            buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
            registry=registry,
        )
        for poller in POLLERS:
            self.poll_success.labels(poller)
            self.poll_duration.labels(poller)
