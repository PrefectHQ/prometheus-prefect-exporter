from collections import defaultdict
from datetime import datetime, timedelta

from metrics.api_metric import Listing, PrefectApiMetric

# State types a run holds before it ends. SCHEDULED includes the Late and
# AwaitingRetry state names.
NON_TERMINAL_STATE_TYPES = ("SCHEDULED", "PENDING", "RUNNING", "PAUSED", "CANCELLING")


def _api_timestamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class PrefectFlowRuns(PrefectApiMetric):
    """
    PrefectFlowRuns class for interacting with Prefect's flow runs endpoints.
    """

    uri = "flow_runs"
    default_sort = "ID_DESC"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # None until the first probe of /flow_runs/filter-minimal answers.
        self.filter_minimal_supported = None

    def _flow_runs_filter_path(self) -> str:
        """
        Return the flow-run filter path to list with: "flow_runs/filter-minimal"
        where the server has it, else "flow_runs/filter".

        The minimal route omits each run's full state object, which the
        exporter does not read. Open-source servers do not have it. The result of
        one probe is kept for the life of this object; a probe that fails for any other
        reason falls back to the full route, which every server has.
        """
        if self.filter_minimal_supported is None:
            resp = self._post(
                "flow_runs/filter-minimal",
                {"limit": 1, "sort": self.default_sort},
                passthrough_statuses=frozenset({404, 405}),
                attempts=1,
            )
            self.filter_minimal_supported = (
                resp is not None
                and resp.status_code
                not in (
                    404,
                    405,
                )
            )
        if self.filter_minimal_supported:
            return "flow_runs/filter-minimal"
        return "flow_runs/filter"

    def _list_flow_runs(self, base_data: dict) -> Listing:
        return self._get_with_pagination(
            base_data=base_data, path=self._flow_runs_filter_path()
        )

    def get_current_flow_runs(self, now: datetime) -> Listing:
        """
        Get the runs in each non-terminal state type. A SCHEDULED run is
        included only once its expected start time has passed.

        Each state type is listed separately, so a numerous state cannot push
        a rarer one out of a paginated or limited result.

        Args:
            now (datetime): The time that bounds SCHEDULED runs.

        Returns:
            Listing: The runs, de-duplicated by id. Incomplete if any of the
            listings was incomplete.
        """
        runs_by_id = {}
        complete = True
        for state_type in NON_TERMINAL_STATE_TYPES:
            flow_runs_filter = {
                "operator": "and_",
                "state": {"type": {"any_": [state_type]}},
            }
            if state_type == "SCHEDULED":
                flow_runs_filter["expected_start_time"] = {
                    "before_": _api_timestamp(now)
                }
            listing = self._list_flow_runs({"flow_runs": flow_runs_filter})
            complete = complete and listing.complete
            for flow_run in listing:
                # A run that changed state between two listings appears in both;
                # the listings run in order, so the later one is more recent.
                runs_by_id[flow_run.get("id")] = flow_run
        return Listing(runs_by_id.values(), complete=complete)

    def get_failed_flow_runs_info(
        self, limit: int, offset_minutes: int, now: datetime
    ) -> tuple[dict, bool]:
        """
        Get the last N failed flow runs per (deployment_id, flow_id) pair within the window.

        Args:
            limit (int): Maximum number of recent failed runs to return per deployment/flow pair.
            offset_minutes (int): How far back the window starts.
            now (datetime): The end of the window.

        Returns:
            tuple: A mapping of (deployment_id, flow_id, state_name) -> [run_id, ...],
            and whether the listing was complete.
        """
        all_failed = self._list_flow_runs(
            {
                "flow_runs": {
                    "operator": "and_",
                    "state": {"type": {"any_": ["FAILED", "CRASHED"]}},
                    "start_time": {
                        "after_": _api_timestamp(
                            now - timedelta(minutes=offset_minutes)
                        )
                    },
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

        return dict(result), all_failed.complete
