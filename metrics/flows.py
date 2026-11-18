from metrics.api_metric import Listing, PrefectApiMetric


class PrefectFlows(PrefectApiMetric):
    """
    PrefectFlows class for interacting with Prefect's flows endpoints.
    """

    uri = "flows"
    default_sort = "NAME_ASC"

    def get_flows_info(self) -> Listing:
        """
        Get information about Prefect flows.

        Returns:
            Listing: Every flow the listing returned.
        """
        return self._get_with_pagination()
