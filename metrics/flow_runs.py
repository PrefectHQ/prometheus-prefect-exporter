import requests
import time

from datetime import datetime, timedelta, timezone


class PrefectFlowRuns:
    """
    PrefectFlowRuns class for interacting with Prefect's flow runs endpoints.
    """

    def __init__(self, url, headers, max_retries, offset_minutes, logger, uri = "flow_runs") -> None:
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
        self.headers     = headers
        self.uri         = uri
        self.url         = url
        self.max_retries = max_retries
        self.logger      = logger

        # Calculate timestamps for before and after data
        after_data           = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
        self.after_data_fmt  = after_data.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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
                    "after_": f"{self.after_data_fmt}"
                }
            }
        }

        for retry in range(self.max_retries):
            try:
                resp = requests.post(endpoint, headers=self.headers, json=data)
                resp.raise_for_status()
            except requests.exceptions.HTTPError as err:
                self.logger.error(err)
                if retry >= self.max_retries - 1:
                    time.sleep(1)
                    raise SystemExit(err)
            else:
                break

        return resp.json()

    def get_all_flow_runs_info(self) -> dict:
        """
        Get information about all flow runs.

        Returns:
            dict: JSON response containing flow runs information.
        """
        endpoint = f"{self.url}/{self.uri}/filter"
        data = {
            "flow_runs": {
                "operator": "and_",
            }
        }

        for retry in range(self.max_retries):
            try:
                resp = requests.post(endpoint, headers=self.headers, json=data)
                resp.raise_for_status()
            except requests.exceptions.HTTPError as err:
                self.logger.error(err)
                if retry >= self.max_retries - 1:
                    time.sleep(1)
                    raise SystemExit(err)
            else:
                break

        return resp.json()
