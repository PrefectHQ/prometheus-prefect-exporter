import uuid

import requests
import time

from metrics.api_metric import PrefectApiMetric


class PrefectWorkQueues(PrefectApiMetric):
    """
    PrefectWorkQueues class for interacting with Prefect's work queues endpoints.
    """

    def __init__(
        self,
        url,
        headers,
        max_retries,
        logger,
        enable_pagination,
        pagination_limit,
        uri="work_queues",
    ) -> None:
        """
        Initialize the PrefectWorkQueues instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for administrative endpoints. Default is "work_queues".

        """
        super().__init__(
            url=url,
            headers=headers,
            max_retries=max_retries,
            logger=logger,
            enable_pagination=enable_pagination,
            pagination_limit=pagination_limit,
            uri=uri,
        )

    def get_work_queues_info(self) -> list:
        """
        Get information about Prefect's work queues.

        Returns:
            dict: JSON response containing work queues information.

        """
        work_queues_info = self._get_with_pagination()

        for queue_info in work_queues_info:
            queue_info["status_info"] = self.get_work_queue_status_info(
                queue_info["id"]
            )

        return work_queues_info

    def get_work_queue_status_info(self, work_queue_id: uuid.UUID) -> dict:
        """
        Get status information for a specific work queue.

        Args:
            work_queue_id (uuid.UUID): The UUID of the work queue.

        Returns:
            dict: JSON response containing work queue status information.

        """
        endpoint = f"{self.url}/{self.uri}/{work_queue_id}/status"

        for retry in range(self.max_retries):
            try:
                resp = requests.get(endpoint, headers=self.headers)
                resp.raise_for_status()

            except requests.exceptions.HTTPError as err:
                self.logger.error(err)
                if retry >= self.max_retries - 1:
                    time.sleep(1)
                    raise SystemExit(err)
            else:
                break

        return resp.json()
