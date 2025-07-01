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


    def get_flow_runs_minimal(self) -> list:
        """
        Get minimal information about all flow runs using the minimal endpoint.
        This is more memory efficient than fetching full flow run details.

        Returns:
            list: Minimal flow run data including total_run_time.
        """
        minimal_flow_runs = self._post_to_endpoint(
            endpoint_suffix="filter/minimal",
            data={
                "flow_runs": {
                    "operator": "and_",
                }
            }
        )
        
        return minimal_flow_runs

    def get_flow_runs_history(self, history_start: str = None, history_end: str = None) -> dict:
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
        
        if history_start:
            history_data["history_start"] = history_start
        if history_end:
            history_data["history_end"] = history_end
        
        history_response = self._post_to_endpoint(
            endpoint_suffix="history",
            data=history_data
        )
        
        return history_response

    def get_flow_runs_count(self) -> int:
        """
        Get the total count of all flow runs using the minimal endpoint.
        This is more memory efficient than fetching all flow runs.

        Returns:
            int: Total count of flow runs.
        """
        minimal_flow_runs = self.get_flow_runs_minimal()
        return len(minimal_flow_runs)
