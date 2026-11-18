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


RECONNECT_REASONS = ("server_close", "ping_timeout", "error")
EVENT_OUTCOMES = ("counted", "duplicate", "ignored", "malformed", "missing_run_count")


class StreamHealth:
    """The `prefect_exporter_stream_*` metrics that report the event stream's health."""

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.connected = Gauge(
            "prefect_exporter_stream_connected",
            "1 while the event stream socket is open and answering pings",
            registry=registry,
        )
        self.refused = Gauge(
            "prefect_exporter_stream_refused",
            "1 while the server refuses the event stream subscription",
            registry=registry,
        )
        self.last_event_timestamp = Gauge(
            "prefect_exporter_stream_last_event_timestamp_seconds",
            "When the last event arrived, in seconds since the epoch",
            registry=registry,
        )
        self.reconnects = Counter(
            "prefect_exporter_stream_reconnects",
            "Reconnects of the event stream after an unplanned close, by reason",
            ["reason"],
            registry=registry,
        )
        self.disconnected_seconds = Counter(
            "prefect_exporter_stream_disconnected_seconds",
            "Time without an event stream subscription",
            registry=registry,
        )
        self.gap_seconds = Counter(
            "prefect_exporter_stream_gap_seconds",
            "Time in which terminal states may be missing from the counts, "
            "because no replay from the server covered it",
            registry=registry,
        )
        self.backfill_failures = Counter(
            "prefect_exporter_stream_backfill_failures",
            "Connects that the server closed while replaying backfill",
            registry=registry,
        )
        self.events = Counter(
            "prefect_exporter_stream_events",
            "Events received, by outcome: counted, duplicate, ignored or malformed. "
            "missing_run_count is counted in addition to the event's outcome.",
            ["outcome"],
            registry=registry,
        )
        for reason in RECONNECT_REASONS:
            self.reconnects.labels(reason)
        for outcome in EVENT_OUTCOMES:
            self.events.labels(outcome)
