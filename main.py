import os
from prometheus_client import start_http_server
from metrics.metrics import PrefectMetrics


if __name__ == "__main__":
    """
    Main entry point for the PrefectMetrics exporter.
    """

    # Get environment variables or use default values
    exporter_port            = int(os.getenv("EXPORTER_PORT", "8000"))
    offset_minutes           = int(os.getenv("OFFSET_MINUTES", "5"))
    polling_interval_seconds = int(os.getenv("POLLING_INTERVAL_SECONDS", "5"))
    url                      = str(os.getenv("PREFECT_API_URL", "https://app.prefect.cloud/api"))

    # Configure headers for HTTP requests
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/json',
    }

    # Create an instance of the PrefectMetrics class
    metrics = PrefectMetrics(
        polling_interval_seconds = polling_interval_seconds,
        url = url,
        headers = headers,
        offset_minutes = offset_minutes
    )

    # Start the HTTP server to expose Prometheus metrics
    start_http_server(exporter_port)

    # Run the loop to collect Prefect metrics
    metrics.run_metrics_loop()
