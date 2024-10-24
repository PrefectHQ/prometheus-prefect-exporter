from datetime import datetime, timedelta, timezone

from metrics.api_metric import PrefectApiMetric


class PrefectFlowRuns(PrefectApiMetric):
    """
    PrefectFlowRuns class for interacting with Prefect's flow runs endpoints.
    """

    def __init__(
        self,
        url,
        headers,
        max_retries,
        offset_minutes,
        logger,
        enable_pagination,
        pagination_limit,
        uri="flow_runs",
    ) -> None:
        """
        Initialize the PrefectFlowRuns instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            offset_minutes (int): Time offset in minutes.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            uri (str, optional): The URI path for flow runs endpoints. Default is "flow_runs".

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

        # Calculate timestamps for before and after data
        after_data = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
        self.after_data_fmt = after_data.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def get_flow_runs_info(self) -> list:
        """
        Get information about flow runs within a specified time range.

        Returns:
            dict: JSON response containing flow runs information.

        """
        flow_runs = self._get_with_pagination(
            base_data={
                "flow_runs": {
                    "operator": "and_",
                    "start_time": {"after_": f"{self.after_data_fmt}"},
                }
            }
        )

        return flow_runs

    def get_all_flow_runs_info(self) -> list:
        """
        Get information about all flow runs.

        Returns:
            dict: JSON response containing flow runs information.
        """
        all_flow_runs = self._get_with_pagination()

        return all_flow_runs
