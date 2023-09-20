import requests


class PrefectAdmin:
    """
    PrefectAdmin class for interacting with Prefect's administrative endpoints.
    """


    def __init__(self, url, headers, uri = "admin") -> None:
        """
        Initialize the PrefectAdmin instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            uri (str, optional): The URI path for administrative endpoints. Default is "admin".

        """
        self.headers = headers
        self.uri     = uri
        self.url     = url


    def get_admin_info(self):
        """
        Get information about the Prefect admin.

        Returns:
            dict: JSON response containing admin information.

        """
        endpoint = f"{self.url}/{self.uri}/version"
        resp = requests.get(endpoint, headers=self.headers)

        return resp.json()
