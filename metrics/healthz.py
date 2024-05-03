import requests
import time


class PrefectHealthz:
    """
    PrefectHealthz class for interacting with Prefect's health endpoints.
    """

    def __init__(self, url, headers, max_retries, logger, uri=None) -> None:
        """
        Initialize the PrefectHealthz instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for health endpoint. Default is None.

        """
        self.headers = headers
        self.uri = uri
        self.url = url
        self.max_retries = max_retries
        self.logger = logger

    def get_health_check(self) -> None:
        """
        Get status about Prefect flows.

        Returns:
            None.

        """
        endpoint = f"{self.url}/health"

        for retry in range(self.max_retries):
            try:
                resp = requests.get(endpoint, headers=self.headers)
                resp.raise_for_status()
                self.logger.info(
                    f"Prefect health check: {resp.status_code} - {resp.reason}"
                )
            except requests.exceptions.HTTPError as err:
                self.logger.error(err)
                if retry >= self.max_retries - 1:
                    time.sleep(1)
                    raise SystemExit(err)
            else:
                break
