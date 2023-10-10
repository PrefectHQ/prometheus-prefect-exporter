import requests
import time


class PrefectDeployments:
    """
    PrefectDeployments class for interacting with Prefect's deployments endpoints.
    """

    def __init__(self, url, headers, max_retries, logger, uri = "deployments") -> None:
        """
        Initialize the PrefectDeployments instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for deployments endpoints. Default is "deployments".

        """
        self.headers     = headers
        self.uri         = uri
        self.url         = url
        self.max_retries = max_retries
        self.logger      = logger


    def get_deployments_count(self) -> dict:
        """
        Get the count of Prefect deployments.

        Returns:
            dict: JSON response containing the count of deployments.

        """
        endpoint = f"{self.url}/{self.uri}/count"

        for retry in range(self.max_retries):
            try:
                resp = requests.post(endpoint, headers=self.headers)
                resp.raise_for_status()
            except requests.exceptions.HTTPError as err:
                self.logger.error(err)
                if retry >= self.max_retries - 1:
                    time.sleep(1)
                    raise SystemExit(err)
            else:
                break

        return resp.json()


    def get_deployments_info(self) -> dict:
        """
        Get information about Prefect deployments.

        Returns:
            dict: JSON response containing information about deployments.

        """
        endpoint = f"{self.url}/{self.uri}/filter"

        for retry in range(self.max_retries):
            try:
                resp = requests.post(endpoint, headers=self.headers)
                resp.raise_for_status()
            except requests.exceptions.HTTPError as err:
                self.logger.error(err)
                if retry >= self.max_retries - 1:
                    time.sleep(1)
                    raise SystemExit(err)
            else:
                break

        return resp.json()
