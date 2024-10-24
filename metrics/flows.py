from metrics.api_metric import PrefectApiMetric


class PrefectFlows(PrefectApiMetric):
    """
    PrefectFlows class for interacting with Prefect's flows endpoints.
    """

    def __init__(
        self,
        url,
        headers,
        max_retries,
        logger,
        enable_pagination,
        pagination_limit,
        uri="flows",
    ) -> None:
        """
        Initialize the PrefectFlows instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for administrative endpoints. Default is "flows".

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

    def get_flows_info(self) -> list:
        """
        Get information about Prefect flows.

        Returns:
            dict: JSON response containing information about flows.

        """
        all_flows = self._get_with_pagination()

        return all_flows
