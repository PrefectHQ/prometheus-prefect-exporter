import time

import requests


class PrefectApiMetric:
    """
    PrefectDeployments class for interacting with Prefect's endpoints
    """

    def __init__(self, url, headers, max_retries, logger, uri) -> None:
        """
        Initialize the PrefectDeployments instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for the intended endpoint.

        """
        self.headers = headers
        self.uri = uri
        self.url = url
        self.max_retries = max_retries
        self.logger = logger

    def _get_with_pagination(self):
        """
        Fetch all items from the endpoint with pagination.

        Returns:
            dict: JSON response containing all items from the endpoint.
        """
        endpoint = f"{self.url}/{self.uri}/filter"
        limit = 200
        offset = 0
        all_items = []

        while True:
            for retry in range(self.max_retries):
                data = {
                    "limit": limit,
                    "offset": offset,
                    "flow_runs": {
                        "operator": "and_",
                    },
                }

                try:
                    resp = requests.post(endpoint, headers=self.headers, json=data)
                    resp.raise_for_status()
                except requests.exceptions.HTTPError as err:
                    self.logger.error(err)
                    if retry >= self.max_retries - 1:
                        time.sleep(1)
                        raise SystemExit(err)
                else:
                    break

            curr_page_flow_runs = resp.json()

            if not curr_page_flow_runs:
                break

            all_items.extend(curr_page_flow_runs)
            offset += limit

        return all_items
