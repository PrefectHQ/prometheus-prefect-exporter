import asyncio
import logging
import threading
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
                **(stream_settings_overrides or {}),
            ),
            FlowRunEventClassifier(
                duplicate_memory_seconds=config.duplicate_memory_hours * 3600
            ),
            self.stream_metrics,
            StreamHealth(registry),
            logger,
            stream_disabled=self._stream_disabled(),
        )
        self.stream_thread = threading.Thread(
            target=lambda: asyncio.run(self.stream.run()),
            name="event-stream",
            daemon=True,
        )

    def _stream_disabled(self) -> bool:
        if self.config.is_cloud:
            return False
        enabled = PrefectAdmin(**self.api_kwargs).stream_out_enabled()
        if enabled is None:
            self.logger.warning(
                "Could not read the server's settings; assuming its event stream "
                "is enabled"
            )
            return False
        return not enabled

    def start(self) -> None:
        self.stream_thread.start()
        for loop in self.loops:
            loop.start()

    def stop(self, timeout: float = 10.0) -> None:
        self.stop_event.set()
        self.stream.stop_threadsafe()
        self.stream_thread.join(timeout)
        for loop in self.loops:
            loop.join(timeout)
