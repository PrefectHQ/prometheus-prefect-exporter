import logging
import time

from prometheus_client import REGISTRY, start_http_server
from pydantic import SecretStr
from pydantic_settings import BaseSettings

from metrics.healthz import PrefectHealthz
from metrics.metrics import PrefectMetrics


class Settings(BaseSettings):
    log_level: str = "INFO"
    max_retries: int = 3
    metrics_port: int = 8000
    offset_minutes: int = 5
    url: str = "http://localhost:4200/api"
    api_key: SecretStr | None = None


if __name__ == "__main__":
    """
    Main entry point for the PrefectMetrics exporter.
    """
    # Load settings from environment variables
    settings = Settings()

    # Configure logging
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("prometheus-prefect-exporter")

    # Configure headers for HTTP requests
    headers = {"accept": "application/json", "Content-Type": "application/json"}

    if api_key := settings.api_key:
        headers["Authorization"] = f"Bearer {api_key.get_secret_value()}"

    # check endpoint
    PrefectHealthz(
        url=settings.url,
        headers=headers,
        max_retries=settings.max_retries,
        logger=logger,
    ).get_health_check()

    # Create an instance of the PrefectMetrics class
    metrics = PrefectMetrics(
        url=settings.url,
        headers=headers,
        offset_minutes=settings.offset_minutes,
        max_retries=settings.max_retries,
        logger=logger,
    )

    # Register the metrics with Prometheus
    logger.info("Inizializing metrics...")
    REGISTRY.register(metrics)

    # Start the HTTP server to expose Prometheus metrics
    start_http_server(settings.metrics_port)
    logger.info(f"Exporter listening on port :{settings.metrics_port}")

    # Run the loop to collect Prefect metrics
    while True:
        time.sleep(5)
