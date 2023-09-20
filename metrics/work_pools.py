import requests


class PrefectWorkPools:
    """
    PrefectWorkPools class for interacting with Prefect's work pools endpoints.
    """


    def __init__(self, url, headers, uri = "work_pools") -> None:
        """
        Initialize the PrefectWorkPools instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            uri (str, optional): The URI path for administrative endpoints. Default is "work_pools".

        """
        self.headers = headers
        self.uri     = uri
        self.url     = url


    def get_work_pools_info(self) -> dict:
        """
        Get information about Prefect's work pools.

        Returns:
            dict: JSON response containing work pools information.

        """
        endpoint = f"{self.url}/{self.uri}/filter"
        resp = requests.post(endpoint, headers=self.headers)

        return resp.json()
