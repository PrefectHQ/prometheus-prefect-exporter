from metrics.api_metric import PrefectApiMetric


class PrefectWorkPools(PrefectApiMetric):
    """
    PrefectWorkPools class for interacting with Prefect's work pools endpoints.
    """

    def __init__(
        self,
        url,
        headers,
        max_retries,
        logger,
        enable_pagination,
        pagination_limit,
        uri="work_pools",
    ) -> None:
        """
        Initialize the PrefectWorkPools instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for administrative endpoints. Default is "work_pools".

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

    def get_work_pools_info(self) -> list:
        """
        Get information about Prefect's work pools.

        Returns:
            dict: JSON response containing work pools information.

        """
        all_work_pools = self._get_with_pagination()

        return all_work_pools
