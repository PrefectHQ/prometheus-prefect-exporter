import logging
import requests
import time


class PrefectWorkQueues:
    """
    PrefectWorkQueues class for interacting with Prefect's work queues endpoints.
    """

    def __init__(self, url, headers, max_retries, logger, uri = "work_queues") -> None:
        """
        Initialize the PrefectWorkQueues instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for administrative endpoints. Default is "work_queues".

        """
        self.headers     = headers
        self.uri         = uri
        self.url         = url
        self.max_retries = max_retries
        self.logger      = logger


    def get_work_queues_info(self) -> dict:
        """
        Get information about Prefect's work queues.

        Returns:
            dict: JSON response containing work queues information.

        """
        endpoint = f"{self.url}/{self.uri}/filter"

        for retry in range(self.max_retries):
            try:
                resp = requests.post(endpoint, headers=self.headers)
                resp = resp.json()
            except requests.exceptions.HTTPError as err:
                self.logger.error(err)
                if retry >= self.max_retries - 1:
                    time.sleep(1)
                    raise SystemExit(err)
            else:
                break

        return resp
