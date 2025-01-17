import os
import base64
import logging
import time
import uuid

from metrics.metrics import PrefectMetrics
from metrics.healthz import PrefectHealthz
from prometheus_client import start_http_server, REGISTRY


def metrics():
    """
    Main entry point for the PrefectMetrics exporter.
    """

    # Get environment variables or use default values
    loglevel = str(os.getenv("LOG_LEVEL", "INFO"))
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    metrics_addr = os.getenv("METRICS_ADDR", "0.0.0.0")
    metrics_port = int(os.getenv("METRICS_PORT", "8000"))
    offset_minutes = int(os.getenv("OFFSET_MINUTES", "3"))
    url = str(os.getenv("PREFECT_API_URL", "http://localhost:4200/api"))
    api_key = str(os.getenv("PREFECT_API_KEY", ""))
    api_auth_string = str(os.getenv("PREFECT_API_AUTH_STRING", ""))
    csrf_client_id = str(uuid.uuid4())
    scrape_interval_seconds = int(os.getenv("SCRAPE_INTERVAL_SECONDS", "30"))
    # Configure logging
    logging.basicConfig(
        level=loglevel, format="%(asctime)s - %(name)s - [%(levelname)s] %(message)s"
    )
    logger = logging.getLogger("prometheus-prefect-exporter")

    # Configure headers for HTTP requests
    headers = {"accept": "application/json", "Content-Type": "application/json"}

    if api_auth_string:
        api_auth_string_encoded = base64.b64encode(api_auth_string.encode("utf-8")).decode("utf-8")
        headers["Authorization"] = f"Basic {api_auth_string_encoded}"
        logger.info("Added Basic Authorization header for PREFECT_API_AUTH_STRING")

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        logger.info("Added Bearer Authorization header for PREFECT_API_KEY")

    # check endpoint
    PrefectHealthz(
        url=url, headers=headers, max_retries=max_retries, logger=logger
    ).get_health_check()

    ##
    # NOTIFY IF PAGINATION IS ENABLED
    #
    enable_pagination = str(os.getenv("PAGINATION_ENABLED", "True")) == "True"
    pagination_limit = int(os.getenv("PAGINATION_LIMIT", 200))
    if enable_pagination:
        logger.info("Pagination is enabled")
        logger.info(f"Pagination limit is {pagination_limit}")
    else:
        logger.info("Pagination is disabled")

    # Create an instance of the PrefectMetrics class
    metrics = PrefectMetrics(
        url=url,
        headers=headers,
        offset_minutes=offset_minutes,
        max_retries=max_retries,
        client_id=csrf_client_id,
        csrf_enabled=str(os.getenv("PREFECT_CSRF_ENABLED", "False")) == "True",
        logger=logger,
        # Enable pagination if not specified to avoid breaking existing deployments
        enable_pagination=enable_pagination,
        pagination_limit=pagination_limit,
    )

    # Register the metrics with Prometheus
    logger.info("Initializing metrics...")
    REGISTRY.register(metrics)

    # Start the HTTP server to expose Prometheus metrics
    start_http_server(metrics_port, metrics_addr)
    logger.info(f"Exporter listening on {metrics_addr}:{metrics_port}")

    # Run the loop to collect Prefect metrics
    while True:
        time.sleep(scrape_interval_seconds)


if __name__ == "__main__":
    metrics()
