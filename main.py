import logging
import os
import threading
import uuid

from prometheus_client import REGISTRY, start_http_server

from metrics.api_metric import PrefectApiMetric
from metrics.collector import PolledMetricsCollector
from metrics.config import Config
from metrics.csrf import CsrfSession
from metrics.health import ExporterHealth
from metrics.healthz import PrefectHealthz
from metrics.inventory import InventoryPoller
from metrics.poller import PollLoop
from metrics.run_gauges import RunGaugePoller
from metrics.stream.counters import FlowRunStreamMetrics


def metrics():
    """
    Main entry point for the PrefectMetrics exporter.
    """
    config = Config.from_env()
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s - %(name)s - [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("prometheus-prefect-exporter")
    if "OFFSET_MINUTES" in os.environ:
        logger.warning("OFFSET_MINUTES is no longer used and is ignored")

    headers = config.headers()

    PrefectHealthz(
        url=config.url,
        headers=headers,
        max_retries=config.max_retries,
        logger=logger,
        timeout=config.request_timeout,
    ).get_health_check()

    health = ExporterHealth(REGISTRY)
    api_kwargs = dict(
        url=config.url,
        headers=headers,
        max_retries=config.max_retries,
        logger=logger,
        enable_pagination=config.enable_pagination,
        pagination_limit=config.pagination_limit,
        timeout=config.request_timeout,
        health=health,
    )
    if config.csrf_enabled:
        token_api = PrefectApiMetric(**api_kwargs)
        client_id = str(uuid.uuid4())
        api_kwargs["csrf"] = CsrfSession(
            client_id, lambda: token_api.get_csrf_token(client_id)
        )

    stream_metrics = FlowRunStreamMetrics(REGISTRY)

    stop = threading.Event()
    inventory = InventoryPoller(
        api_kwargs,
        failed_runs_offset_minutes=config.failed_runs_offset_minutes,
        failed_runs_limit=config.failed_runs_limit,
        on_inventory=stream_metrics.precreate,
    )
    runs = RunGaugePoller(
        api_kwargs,
        inventory_names=lambda: inventory.names,
        enable_flow_run_name_label=config.enable_flow_run_name_label,
        logger=logger,
    )
    loops = [
        PollLoop(
            "inventory",
            inventory.poll,
            config.inventory_poll_interval,
            health,
            stop,
            logger,
        ),
        PollLoop("runs", runs.poll, config.run_poll_interval, health, stop, logger),
    ]
    REGISTRY.register(PolledMetricsCollector(loops))

    start_http_server(config.metrics_port, config.metrics_addr)
    logger.info(f"Exporter listening on {config.metrics_addr}:{config.metrics_port}")
    for loop in loops:
        loop.start()

    try:
        stop.wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        stop.set()


if __name__ == "__main__":
    metrics()
