from metrics.api_metric import Listing, PrefectApiMetric


class PrefectWorkPools(PrefectApiMetric):
    """
    PrefectWorkPools class for interacting with Prefect's work pools endpoints.
    """

    uri = "work_pools"

    def get_work_pools_info(self) -> Listing:
        """
        Get information about Prefect's work pools.

        Returns:
            Listing: Every work pool the listing returned.
        """
        return self._get_with_pagination()
