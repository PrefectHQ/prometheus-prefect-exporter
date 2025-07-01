from datetime import datetime, timedelta, timezone
import pendulum

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

    def get_flow_runs_minimal(self) -> list:
        """
        Get minimal information about all flow runs using the standard filter endpoint.
        This is compatible with both Prefect Cloud and OSS.

        Returns:
            list: Flow run data from filter endpoint.
        """
        flow_runs = self._post_to_endpoint(
            endpoint_suffix="filter",
            data={
                "flow_runs": {
                    "operator": "and_",
                }
            }
        )
        
        return flow_runs

    def get_flow_runs_history(
        self, history_start: str = "", history_end: str = ""
    ) -> dict:
        """
        Get flow run history and aggregated metrics using the history endpoint.
        This provides server-side aggregations without loading all flow run data.

        Args:
            history_start (str): Start time for history window (ISO format).
            history_end (str): End time for history window (ISO format).

        Returns:
            dict: Flow run history and aggregated metrics.
        """
        history_data = {
            "flow_runs": {
                "operator": "and_",
            }
        }

        if not history_start:
            history_start = str(pendulum.now("UTC"))

        if not history_end:
            history_end = str(pendulum.now("UTC") + timedelta(days=1))

        history_response = self._post_to_endpoint(
            endpoint_suffix="history", data=history_data
        )

        return history_response

    def get_flow_runs_count(self) -> int:
        """
        Get the total count of all flow runs using the count endpoint.
        This is compatible with both Prefect Cloud and OSS.

        Returns:
            int: Total count of flow runs.
        """
        count_response = self._post_to_endpoint(
            endpoint_suffix="count",
        )

        # Count endpoint returns just an integer
        if isinstance(count_response, int):
            return count_response
        elif isinstance(count_response, dict) and "count" in count_response:
            return count_response["count"]
        else:
            return 0
