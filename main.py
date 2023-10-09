import os
import logging

from prometheus_client import start_http_server, CollectorRegistry, generate_latest
from metrics.metrics import PrefectMetrics


if __name__ == "__main__":
    """
    Main entry point for the PrefectMetrics exporter.
    """

    # Get environment variables or use default values
    metrics_port             = int(os.getenv("METRICS_PORT", "8000"))
    max_retries              = int(os.getenv("MAX_RETRIES", "3"))
    offset_minutes           = int(os.getenv("OFFSET_MINUTES", "5"))
    polling_interval_seconds = int(os.getenv("POLLING_INTERVAL_SECONDS", "30"))
    url                      = str(os.getenv("PREFECT_API_URL", "https://app.prefect.cloud/api"))
    loglevel                 = str(os.getenv("LOG_LEVEL", "INFO"))

    # Configure logging
    logging.basicConfig(level=loglevel, format='%(asctime)s - %(name)s - [%(levelname)s] %(message)s')
    logger = logging.getLogger("prometheus-prefect-exporter")

    # Configure headers for HTTP requests
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/json',
    }

    registry = CollectorRegistry()

    # Create an instance of the PrefectMetrics class
    metrics = PrefectMetrics(
        polling_interval_seconds = polling_interval_seconds,
        url = url,
        headers = headers,
        offset_minutes = offset_minutes,
        registry = registry,
        max_retries = max_retries,
        logger = logger
    )

    # Start the HTTP server to expose Prometheus metrics
    start_http_server(metrics_port, registry=registry)

    # Log the port the exporter is listening on
    logger.info(f"Exporter listening on port :{metrics_port}")

    # Run the loop to collect Prefect metrics
    metrics.run_metrics_loop()
