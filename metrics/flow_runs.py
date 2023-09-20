import requests
from datetime import datetime, timedelta, timezone


class PrefectFlowRuns:
    """
    PrefectFlowRuns class for interacting with Prefect's flow runs endpoints.
    """

    def __init__(self, url, headers, offset_minutes, uri = "flow_runs") -> None:
        """
        Initialize the PrefectFlowRuns instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            offset_minutes (int): Time offset in minutes.
            uri (str, optional): The URI path for flow runs endpoints. Default is "flow_runs".

        """
        self.headers = headers
        self.uri     = uri
        self.url     = url

        # Calculate timestamps for before and after data
        before_data          = datetime.now(timezone.utc)
        self.before_data_fmt = before_data.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        after_data           = before_data - timedelta(minutes=offset_minutes)
        self.after_data_fmt  = after_data.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


    def get_flow_runs_count(self) -> dict:
        """
        Get the count of flow runs.

        Returns:
            dict: JSON response containing the count of flow runs.

        """
        endpoint = f"{self.url}/{self.uri}/count"
        resp = requests.post(endpoint, headers=self.headers)

        return resp.json()


    def get_flow_runs_info(self) -> dict:
        """
        Get information about flow runs within a specified time range.

        Returns:
            dict: JSON response containing flow runs information.

        """
        endpoint = f"{self.url}/{self.uri}/filter"
        data = {
            "flow_runs": {
                "operator": "and_",
                "start_time": {
                    "before_": f"{self.before_data_fmt}",
                    "after_": f"{self.after_data_fmt}"
                }
            }
        }
        resp = requests.post(endpoint, headers=self.headers, json=data)

        return resp.json()


        ## TODO
        # - Review output for properly metric
        #
        # def get_flow_runs_history(self) -> dict:
        #     """
        #     """
        #     endpoint = f"{self.url}/{self.uri}/history"
        #
        #     data = {
        #         "history_start": f"{self.after_data_fmt}",
        #         "history_end": f"{self.before_data_fmt}",
        #         "history_interval_seconds": 43200,
        #         "flow_runs": {}
        #     }
        #
        #     resp = requests.post(endpoint, headers=self.headers, json=data)
        #
        #     return resp.json()
