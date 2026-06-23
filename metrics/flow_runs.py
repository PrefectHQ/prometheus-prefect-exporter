from collections import defaultdict
from datetime import datetime, timedelta, timezone

from metrics.api_metric import PrefectApiMetric


class PrefectFlowRuns(PrefectApiMetric):
    """
    PrefectFlowRuns class for interacting with Prefect's flow runs endpoints.
    """

    # All terminal/non-terminal state types Prefect can report. get_flow_runs_info()
    # queries each group separately so a high-volume state (e.g. COMPLETED) cannot crowd
    # rarer states (FAILED/CRASHED) out of a limited/paginated result window.
    # See https://github.com/PrefectHQ/prometheus-prefect-exporter/issues/113 and the
    # upstream diagnosis in https://github.com/PrefectHQ/prefect/issues/20341.
    STATE_TYPES = [
        "SCHEDULED",
        "PENDING",
        "RUNNING",
        "PAUSED",
        "CANCELLING",
        "CANCELLED",
        "COMPLETED",
        "FAILED",
        "CRASHED",
    ]

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

        Queries each state type separately and merges the results. A single
        unfiltered query is sorted by start_time and capped by the page/pagination
        limit, so the most numerous state (typically COMPLETED) can push rarer
        FAILED/CRASHED runs out of the returned window, under-counting them in
        ``prefect_info_flow_runs``. Splitting per state bounds each query by that
        state's own volume, so no state is silently truncated.

        Returns:
            list: Flow runs across all state types, de-duplicated by run id.

        """
        flow_runs_by_id = {}
        for state_type in self.STATE_TYPES:
            for flow_run in self._get_with_pagination(
                base_data={
                    "flow_runs": {
                        "operator": "and_",
                        "start_time": {"after_": f"{self.after_data_fmt}"},
                        "state": {"type": {"any_": [state_type]}},
                    }
                }
            ):
                # A run can only hold one state, but de-dupe by id defensively so a
                # run observed transitioning between queries is never double-counted.
                flow_runs_by_id[flow_run.get("id")] = flow_run

        return list(flow_runs_by_id.values())

    def get_all_flow_runs_info(self) -> list:
        """
        Get information about all flow runs.

        Returns:
            dict: JSON response containing flow runs information.
        """
        all_flow_runs = self._get_with_pagination(
            base_data={
                "flow_runs": {
                    "operator": "and_",
                    "end_time": {"after_": f"{self.after_data_fmt}"},
                }
            }
        )

        return all_flow_runs

    def get_ongoing_flow_runs_info(self) -> list:
        """
        Get information about ongoing flow runs

        Returns:
            dict: JSON response containing ongoing flow runs information.
        """
        ongoing_flow_runs = self._get_with_pagination(
            base_data={
                "flow_runs": {
                    "operator": "and_",
                    "end_time": {"is_null_": True},
                    "state": {"type": {"any_": ["RUNNING", "PENDING", "SCHEDULED"]}},
                }
            }
        )

        return ongoing_flow_runs

    def get_failed_flow_runs_info(self, limit: int) -> dict:
        """
        Get the last N failed flow runs per (deployment_id, flow_id) pair within the window.

        Args:
            limit (int): Maximum number of recent failed runs to return per deployment/flow pair.

        Returns:
            dict: Mapping of (deployment_id, flow_id, state_name) -> [run_id, ...]
        """
        all_failed = self._get_with_pagination(
            base_data={
                "flow_runs": {
                    "operator": "and_",
                    "state": {"type": {"any_": ["FAILED", "CRASHED"]}},
                    "start_time": {"after_": f"{self.after_data_fmt}"},
                    "deployment_id": {"is_null_": False},
                },
                "sort": "START_TIME_DESC",
            }
        )

        result = defaultdict(list)
        for flow_run in all_failed:
            key = (
                flow_run.get("deployment_id"),
                flow_run.get("flow_id"),
                flow_run.get("state_name"),
            )
            if len(result[key]) < limit:
                result[key].append(str(flow_run.get("id", "null")))

        return result
