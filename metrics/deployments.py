from metrics.api_metric import PrefectApiMetric


class PrefectDeployments(PrefectApiMetric):
    """
    PrefectDeployments class for interacting with Prefect's deployments endpoints.
    """

    def __init__(self, url, headers, max_retries, logger, uri="deployments") -> None:
        """
        Initialize the PrefectDeployments instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for deployments endpoints. Default is "deployments".

        """
        super().__init__(
            url=url, headers=headers, max_retries=max_retries, logger=logger, uri=uri
        )

    def get_deployments_info(self) -> dict:
        """
        Get information about Prefect deployments.

        Returns:
            dict: JSON response containing information about deployments.

        """
        all_deployments = self._get_with_pagination()

        return all_deployments
