import time
from typing import Optional

import requests


class PrefectApiMetric:
    """
    PrefectDeployments class for interacting with Prefect's endpoints
    """

    def __init__(
        self,
        url,
        headers,
        max_retries,
        logger,
        enable_pagination,
        pagination_limit,
        uri,
    ) -> None:
        """
        Initialize the PrefectDeployments instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for the intended endpoint.
            enable_pagination (bool): Whether to use pagination or not.
            pagination_limit (int): The limit for pagination.
        """
        self.headers = headers
        self.uri = uri
        self.url = url
        self.max_retries = max_retries
        self.logger = logger
        self.enable_pagination = enable_pagination
        self.pagination_limit = pagination_limit

    def _get_with_pagination(self, base_data: Optional[dict] = None) -> list:
        """
        Fetch all items from the endpoint with pagination.

        Returns:
            dict: JSON response containing all items from the endpoint.
        """
        endpoint = f"{self.url}/{self.uri}/filter"
        enable_pagination = self.enable_pagination
        limit = self.pagination_limit
        offset = 0
        all_items = []

        # Run the loop until the current page is empty
        while True:
            for retry in range(self.max_retries):
                data = {
                    **(base_data or {}),
                    "limit": limit,
                    "offset": offset,
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

            curr_page_items = resp.json()

            # If pagination is not used, break the loop
            if not enable_pagination:
                break

            # If the current page is empty, break the loop
            if not curr_page_items:
                break

            all_items.extend(curr_page_items)
            offset += limit

        return all_items
