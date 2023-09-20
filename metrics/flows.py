import requests


class PrefectFlows:
    """
    PrefectFlows class for interacting with Prefect's flows endpoints.
    """

    def __init__(self, url, headers, uri = "flows") -> None:
        """
        Initialize the PrefectFlows instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            uri (str, optional): The URI path for administrative endpoints. Default is "flows".

        """
        self.headers = headers
        self.uri     = uri
        self.url     = url


    def get_flows_count(self) -> dict:
        """
        Get the count of Prefect flows.

        Returns:
            dict: JSON response containing the count of flows.

        """
        endpoint = f"{self.url}/{self.uri}/count"
        resp = requests.post(endpoint, headers=self.headers)

        return resp.json()


    def get_flows_info(self) -> dict:
        """
        Get information about Prefect flows.

        Returns:
            dict: JSON response containing information about flows.

        """
        endpoint = f"{self.url}/{self.uri}/filter"
        resp = requests.post(endpoint, headers=self.headers)

        return resp.json()
