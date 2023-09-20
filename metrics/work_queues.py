import requests


class PrefectWorkQueues:
    """
    PrefectWorkQueues class for interacting with Prefect's work queues endpoints.
    """

    def __init__(self, url, headers, uri = "work_queues") -> None:
        """
        Initialize the PrefectWorkQueues instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            uri (str, optional): The URI path for administrative endpoints. Default is "work_queues".

        """
        self.headers = headers
        self.uri     = uri
        self.url     = url


    def get_work_queues_info(self) -> dict:
        """
        Get information about Prefect's work queues.

        Returns:
            dict: JSON response containing work queues information.

        """
        endpoint = f"{self.url}/{self.uri}/filter"
        resp = requests.post(endpoint, headers=self.headers)

        return resp.json()
