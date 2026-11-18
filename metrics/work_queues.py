import uuid

from metrics.api_metric import Listing, PrefectApiMetric


class PrefectWorkQueues(PrefectApiMetric):
    """
    PrefectWorkQueues class for interacting with Prefect's work queues endpoints.
    """

    uri = "work_queues"

    def get_work_queues_info(self) -> Listing:
        """
        Get information about Prefect's work queues, each with its status
        under `status_info`.

        Returns:
            Listing: Every work queue the listing returned.
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
            dict: JSON response containing work queue status information,
                  or an empty dict when every attempt failed.
        """
        resp = self._get(
            f"{self.uri}/{work_queue_id}/status", f"/{self.uri}/{{id}}/status"
        )
        return {} if resp is None else resp.json()
