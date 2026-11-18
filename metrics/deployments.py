from metrics.api_metric import Listing, PrefectApiMetric


class PrefectDeployments(PrefectApiMetric):
    """
    PrefectDeployments class for interacting with Prefect's deployments endpoints.
    """

    uri = "deployments"
    default_sort = "NAME_ASC"

    def get_deployments_info(self) -> Listing:
        """
        Get information about Prefect deployments.

        Returns:
            Listing: Every deployment the listing returned.
        """
        return self._get_with_pagination()
