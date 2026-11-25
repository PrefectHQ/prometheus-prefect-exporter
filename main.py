import logging
import os
import signal
import threading

from prometheus_client import REGISTRY, start_http_server

from metrics.config import Config
from metrics.exporter import Exporter


def with_health_endpoint(app):
    """
    Wrap a WSGI app so that GET /health answers 200 while the process is up.
    """

    def app_with_health(environ, start_response):
        if environ["REQUEST_METHOD"] == "GET" and environ["PATH_INFO"] == "/health":
            # Leaves out stream state: a restart because of it would lose counts.
            start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"OK"]
        return app(environ, start_response)

    return app_with_health


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
    httpd, _ = start_http_server(config.metrics_port, config.metrics_addr)
    httpd.set_app(with_health_endpoint(httpd.get_app()))
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
