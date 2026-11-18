import asyncio
import logging
import threading
import time
import uuid

from prometheus_client import CollectorRegistry

from metrics.admin import PrefectAdmin
from metrics.api_metric import PrefectApiMetric
from metrics.collector import PolledMetricsCollector
from metrics.config import Config
from metrics.csrf import CsrfSession
from metrics.health import ExporterHealth, StreamHealth
from metrics.inventory import InventoryPoller
from metrics.poller import PollLoop
from metrics.run_gauges import RunGaugePoller
from metrics.stream.classifier import FlowRunEventClassifier
from metrics.stream.client import EventStream, StreamSettings
from metrics.stream.counters import FlowRunStreamMetrics


STREAM_RESTART_DELAY_SECONDS = 5.0
# One short attempt: the read repeats at the next connect if it fails.
STREAM_SETTINGS_TIMEOUT_SECONDS = 10.0


class Exporter:
    """
    The exporter's background work: the inventory and run poll loops, and the
    event stream on its own thread. `/metrics` reads what they store in
    `registry`.
    """

    def __init__(
        self,
        config: Config,
        registry: CollectorRegistry,
        logger: logging.Logger,
        stream_settings_overrides: dict | None = None,
    ) -> None:
        """
        Args:
            config (Config): The exporter's settings.
            registry (CollectorRegistry): Where every metric is registered.
            logger (logging.Logger): The logger.
            stream_settings_overrides (dict, optional): Replaces stream timing
                settings, for tests.
        """
        self.config = config
        self.logger = logger
        self.stop_event = threading.Event()

        self.health = ExporterHealth(registry)
        api_kwargs = dict(
            url=config.url,
            headers=config.headers(),
            max_retries=config.max_retries,
            logger=logger,
            enable_pagination=config.enable_pagination,
            pagination_limit=config.pagination_limit,
            timeout=config.request_timeout,
            health=self.health,
        )
        if config.csrf_enabled:
            token_api = PrefectApiMetric(**api_kwargs)
            client_id = str(uuid.uuid4())
            api_kwargs["csrf"] = CsrfSession(
                client_id, lambda: token_api.get_csrf_token(client_id)
            )
        self.api_kwargs = api_kwargs

        self.stream_metrics = FlowRunStreamMetrics(registry)
        self.inventory = InventoryPoller(
            api_kwargs,
            failed_runs_offset_minutes=config.failed_runs_offset_minutes,
            failed_runs_limit=config.failed_runs_limit,
            on_inventory=self.stream_metrics.precreate,
        )
        self.runs = RunGaugePoller(
            api_kwargs,
            inventory_names=lambda: self.inventory.names,
            enable_flow_run_name_label=config.enable_flow_run_name_label,
            logger=logger,
        )
        self.loops = [
            PollLoop(
                "inventory",
                self.inventory.poll,
                config.inventory_poll_interval,
                self.health,
                self.stop_event,
                logger,
            ),
            PollLoop(
                "runs",
                self.runs.poll,
                config.run_poll_interval,
                self.health,
                self.stop_event,
                logger,
            ),
        ]
        registry.register(PolledMetricsCollector(self.loops))

        self.stream = EventStream(
            StreamSettings(
                api_url=config.url,
                token=config.stream_token,
                backfill_window=config.backfill_window_seconds,
                refusal_hint=(
                    "On Prefect Cloud the API key needs the see_events scope."
                    if config.is_cloud
                    else ""
                ),
                **(stream_settings_overrides or {}),
            ),
            FlowRunEventClassifier(
                duplicate_memory_seconds=config.duplicate_memory_hours * 3600
            ),
            self.stream_metrics,
            StreamHealth(registry),
            logger,
            read_stream_out_enabled=(
                None
                if config.is_cloud
                else PrefectAdmin(
                    **{
                        **self.api_kwargs,
                        "max_retries": 1,
                        "timeout": STREAM_SETTINGS_TIMEOUT_SECONDS,
                    }
                ).stream_out_enabled
            ),
        )
        self.stream_thread = threading.Thread(
            target=self._run_stream, name="event-stream", daemon=True
        )

    def _run_stream(self) -> None:
        # The stream catches its own errors; this restarts it if one still
        # escapes, so the thread never ends while the exporter runs.
        while not self.stop_event.is_set():
            try:
                asyncio.run(self.stream.run())
            except Exception:
                self.logger.exception("The event stream stopped; restarting it")
            if self.stop_event.wait(STREAM_RESTART_DELAY_SECONDS):
                return

    def start(self) -> None:
        self.stream_thread.start()
        for loop in self.loops:
            loop.start()

    def stop(self, timeout: float = 10.0) -> None:
        """
        Stop the background work, waiting at most `timeout` seconds in all.
        Threads still blocked on the API after that are daemon threads and end
        with the process.
        """
        deadline = time.monotonic() + timeout
        self.stop_event.set()
        self.stream.stop_threadsafe()
        for thread in (self.stream_thread, *self.loops):
            thread.join(max(0.0, deadline - time.monotonic()))
