import requests


class PrefectDeployments:
    """
    PrefectDeployments class for interacting with Prefect's deployments endpoints.
    """

    def __init__(self, url, headers, uri = "deployments") -> None:
        """
        Initialize the PrefectDeployments instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            uri (str, optional): The URI path for deployments endpoints. Default is "deployments".

        """
        self.headers = headers
        self.uri     = uri
        self.url     = url


    def get_deployments_count(self) -> dict:
        """
        Get the count of Prefect deployments.

        Returns:
            dict: JSON response containing the count of deployments.

        """
        endpoint = f"{self.url}/{self.uri}/count"
        resp = requests.post(endpoint, headers=self.headers)

        return resp.json()


    def get_deployments_info(self) -> dict:
        """
        Get information about Prefect deployments.

        Returns:
            dict: JSON response containing information about deployments.

        """
        endpoint = f"{self.url}/{self.uri}/filter"
        resp = requests.post(endpoint, headers=self.headers)

        return resp.json()
