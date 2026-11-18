import logging
import os
import signal
import threading

from prometheus_client import REGISTRY, start_http_server

from metrics.config import Config
from metrics.exporter import Exporter


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

    # Serve /metrics first: nothing below waits on the Prefect API.
    start_http_server(config.metrics_port, config.metrics_addr)
    logger.info(f"Exporter listening on {config.metrics_addr}:{config.metrics_port}")
    exporter = Exporter(config, REGISTRY, logger)
    exporter.start()

    shutdown = threading.Event()
    signal.signal(signal.SIGTERM, lambda signum, frame: shutdown.set())
    try:
        shutdown.wait()
    except KeyboardInterrupt:
        pass
    logger.info("Shutting down...")
    exporter.stop()


if __name__ == "__main__":
    metrics()
