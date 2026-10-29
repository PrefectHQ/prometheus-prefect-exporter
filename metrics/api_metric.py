import time
from typing import Optional

import requests

from metrics.retry_after import detect_retry_after, log_retry_after


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

    def _post(self, endpoint: str, data: dict) -> Optional[requests.Response]:
        """
        POST to an endpoint, retrying with exponential backoff.

        Returns:
            requests.Response: The response, or None once retries are exhausted
            or the server sends Retry-After.
        """
        for retry in range(self.max_retries):
            try:
                resp = requests.post(endpoint, headers=self.headers, json=data)
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as err:
                signal = detect_retry_after(err.response)
                if signal is not None:
                    log_retry_after(self.logger, endpoint, signal)
                    return None
                self.logger.error(err)
                if retry < self.max_retries - 1:
                    time.sleep(2**retry)

        self.logger.error("Max retries reached for %s", endpoint)
        return None

    def _get_with_pagination(self, base_data: Optional[dict] = None) -> list:
        """
        Fetch all items from the endpoint with pagination.

        Returns:
            list: All items from the endpoint, or an empty list on failure.
        """
        endpoint = f"{self.url}/{self.uri}/filter"
        enable_pagination = self.enable_pagination
        limit = self.pagination_limit
        offset = 0
        all_items = []

        # Run the loop until the current page is empty
        while True:
            data = {
                **(base_data or {}),
                "limit": limit,
                "offset": offset,
            }
            resp = self._post(endpoint, data)
            if resp is None:
                return all_items

            curr_page_items = resp.json()

            # If the current page is empty, break the loop
            if not curr_page_items:
                break

            # The page has items. Extend the item set.
            all_items.extend(curr_page_items)

            # If pagination is not used, break the loop
            if not enable_pagination:
                break

            offset += limit

        return all_items

    def get_by_ids(self, ids) -> list:
        """
        Fetch only the items with the given IDs.

        Returns:
            list: The items found, omitting any whose request failed.
        """
        ids = sorted({i for i in ids if i is not None})
        items = []
        for start in range(0, len(ids), self.pagination_limit):
            data = {
                self.uri: {"id": {"any_": ids[start : start + self.pagination_limit]}},
                "limit": self.pagination_limit,
            }
            resp = self._post(f"{self.url}/{self.uri}/filter", data)
            if resp is not None:
                items.extend(resp.json())
        return items

    def get_count(self) -> Optional[int]:
        """
        Get the total number of items from the endpoint's count route.

        Returns:
            int: The item count, or None if the request failed.
        """
        resp = self._post(f"{self.url}/{self.uri}/count", {})
        return None if resp is None else resp.json()
