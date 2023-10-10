import requests
import time


class PrefectAdmin:
    """
    PrefectAdmin class for interacting with Prefect's administrative endpoints.
    """


    def __init__(self, url, headers, max_retries, logger, uri = "admin") -> None:
        """
        Initialize the PrefectAdmin instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for administrative endpoints. Default is "admin".

        """
        self.headers     = headers
        self.uri         = uri
        self.url         = url
        self.max_retries = max_retries
        self.logger      = logger


    def get_admin_info(self):
        """
        Get information about the Prefect admin.

        Returns:
            dict: JSON response containing admin information.

        """
        endpoint = f"{self.url}/{self.uri}/version"

        for retry in range(self.max_retries):
            try:
                resp = requests.get(endpoint, headers=self.headers)
                resp = resp.json()
            except requests.exceptions.HTTPError as err:
                self.logger.error(err)
                if retry >= self.max_retries - 1:
                    time.sleep(1)
                    raise SystemExit(err)
            else:
                break

        return resp
