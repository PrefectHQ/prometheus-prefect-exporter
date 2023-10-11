import time

from metrics.admin import PrefectAdmin
from metrics.deployments import PrefectDeployments
from metrics.flow_runs import PrefectFlowRuns
from metrics.flows import PrefectFlows
from metrics.work_pools import PrefectWorkPools
from metrics.work_queues import PrefectWorkQueues
from metrics.healthz import PrefectHealthz
from prometheus_client import Gauge, Info, Enum


class PrefectMetrics:
    """
    PrefectMetrics class for collecting and exposing Prometheus metrics related to Prefect.
    """


    def __init__(self, url, headers, offset_minutes, polling_interval_seconds, max_retries, logger) -> None:
        """
        Initialize the PrefectMetrics instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            offset_minutes (int): Time offset in minutes.
            polling_interval_seconds (int): The polling interval in seconds.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.

        """
        self.headers                  = headers
        self.offset_minutes           = offset_minutes
        self.polling_interval_seconds = polling_interval_seconds
        self.url                      = url
        self.max_retries              = max_retries
        self.logger                   = logger

        # Prefect admin metrics
        self.prefect_info_admin = Info("prefect_info_admin", "Prefect admin info")

        # Prefect deployments metrics
        self.prefect_deployments = Gauge("prefect_deployments_total", "Prefect total deployments")
        self.prefect_info_deployments = Gauge("prefect_info_deployment", "Prefect deployment info",
                                              [
                                                "created", "flow_id", "flow_name", "deployment_id", "is_schedule_active",
                                                "deployment_name", "path", "work_pool_name", "work_queue_name"
                                              ]
                                             )

        # Prefect flows metrics
        self.prefect_flows = Gauge("prefect_flows_total", "Prefect total flows")
        self.prefect_info_flows = Gauge("prefect_info_flows", "Prefect flow info",
                                        [
                                          "created", "flow_id", "flow_name"
                                        ]
                                       )

        # Prefect flow_runs metrics
        self.prefect_flow_runs = Gauge("prefect_flow_runs_total", "Prefect total flow runs")
        self.prefect_info_flow_runs = Enum("prefect_info_flow_runs", "Prefect flow runs info",
                                        [
                                          "created", "deployment_id", "deployment_name", "end_time", "flow_id",
                                          "flow_name", "flow_run_id", "flow_run_name", "run_count", "start_time", "state_id",
                                          "total_run_time", "work_queue_name"
                                        ],
                                        states=[
                                            "Completed", "Cancelled", "Failed", "Running", "Scheduled",
                                            "Pending", "Crashed", "Cancelling", "Paused", "TimedOut"
                                        ]
                                       )

        # Prefect work_pools metrics
        self.prefect_work_pools = Gauge("prefect_work_pools_total", "Prefect total work pools")
        self.prefect_info_work_pools = Gauge("prefect_info_work_pools", "Prefect work pools info",
                                        [
                                          "created", "work_queue_id", "work_pool_id", "is_paused",
                                          "work_pool_name", "type"
                                        ]
                                       )

        # Prefect work_queues metrics
        self.prefect_work_queues = Gauge("prefect_work_queues_total", "Prefect total work queues")
        self.prefect_info_work_queues = Gauge("prefect_info_work_queues", "Prefect work queues info",
                                        [
                                          "created", "work_queue_id", "is_paused", "work_queue_name", "priority",
                                          "type", "work_pool_id", "work_pool_name"
                                        ]
                                       )


    def get_admin_metrics(self) -> None:
        """
        Get and set Prefect admin metrics.

        """
        admin = PrefectAdmin(self.url, self.headers, self.max_retries, self.logger)

        # set admin metrics
        self.prefect_info_admin.info({'prefect_version': admin.get_admin_info()})


    def get_deployments_metrics(self) -> None:
        """
        Get and set Prefect deployments metrics.

        """
        deployments = PrefectDeployments(self.url, self.headers, self.max_retries, self.logger)

        # set deployments metrics
        self.prefect_deployments.set(deployments.get_deployments_count())
        for deployment in deployments.get_deployments_info():
            # get flow name
            if deployment.get("flow_id") is None:
                flow_name = "null"
            else:
                flow_name = PrefectFlows(
                                    self.url,
                                    self.headers,
                                    self.max_retries,
                                    self.logger
                                ).get_flows_name(deployment.get("flow_id"))

            self.prefect_info_deployments.labels(
                deployment.get("created", "null"),
                deployment.get("flow_id", "null"),
                flow_name,
                deployment.get("id", "null"),
                deployment.get("is_schedule_active", "null"),
                deployment.get("name", "null"),
                deployment.get("path", "null"),
                deployment.get("work_pool_name", "null"),
                deployment.get("work_queue_name", "null")
            ).set(1)


    def get_flows_metrics(self) -> None:
        """
        Get and set Prefect flows metrics.

        """
        flows = PrefectFlows(self.url, self.headers, self.max_retries, self.logger)

        # set flows metrics
        self.prefect_flows.set(flows.get_flows_count())
        for flow in flows.get_flows_info():
            self.prefect_info_flows.labels(
              flow.get("created", "null"),
              flow.get("id", "null"),
              flow.get("name", "null")
            ).set(1)


    def get_flow_runs_metrics(self) -> None:
        """
        Get and set Prefect flow runs metrics.

        """
        flow_runs = PrefectFlowRuns(self.url, self.headers, self.max_retries, self.offset_minutes, self.logger)

        # set flows metrics
        self.prefect_flow_runs.set(flow_runs.get_flow_runs_count())
        for flow_run in flow_runs.get_flow_runs_info():
            # get deployment name
            if flow_run.get("deployment_id") is None:
                deployment_name = "null"
            else:
                deployment_name = PrefectDeployments(
                                    self.url,
                                    self.headers,
                                    self.max_retries,
                                    self.logger
                                ).get_deployments_name(flow_run.get("deployment_id"))
            # get flow name
            if flow_run.get("flow_id") is None:
                flow_name = "null"
            else:
                flow_name = PrefectFlows(
                                    self.url,
                                    self.headers,
                                    self.max_retries,
                                    self.logger
                                ).get_flows_name(flow_run.get("flow_id"))

            self.prefect_info_flow_runs.labels(
                flow_run.get("created", "null"),
                flow_run.get("deployment_id", "null"),
                deployment_name,
                flow_run.get("end_time", "null"),
                flow_run.get("flow_id", "null"),
                flow_name,
                flow_run.get("id", "null"),
                flow_run.get("name", "null"),
                flow_run.get("run_count", "null"),
                flow_run.get("start_time", "null"),
                flow_run.get("state_id", "null"),
                flow_run.get("total_run_time", "null"),
                flow_run.get("work_queue_name", "null")
            ).state(flow_run.get("state_name", "null"))


    def get_work_pools_metrics(self) -> None:
        """
        Get and set Prefect work pools metrics.

        """
        work_pools = PrefectWorkPools(self.url, self.headers, self.max_retries, self.logger)

        # set work_pools metrics
        self.prefect_work_pools.set(len(work_pools.get_work_pools_info()))
        for work_pool in work_pools.get_work_pools_info():
            state = 0 if work_pool.get("is_paused") else 1
            self.prefect_info_work_pools.labels(
                work_pool.get("created", "null"),
                work_pool.get("default_queue_id", "null"),
                work_pool.get("id", "null"),
                work_pool.get("is_paused", "null"),
                work_pool.get("name", "null"),
                work_pool.get("type", "null")
            ).set(state)


    def get_work_queues_metrics(self) -> None:
        """
        Get and set Prefect work queues metrics.

        """
        work_queues = PrefectWorkQueues(self.url, self.headers, self.max_retries, self.logger)

        # set work_queues metrics
        self.prefect_work_queues.set(len(work_queues.get_work_queues_info()))
        for work_queue in work_queues.get_work_queues_info():
            state = 0 if work_queue.get("is_paused") else 1
            self.prefect_info_work_queues.labels(
                work_queue.get("created", "null"),
                work_queue.get("id", "null"),
                work_queue.get("is_paused", "null"),
                work_queue.get("name", "null"),
                work_queue.get("priority", "null"),
                work_queue.get("type", "null"),
                work_queue.get("work_pool_id", "null"),
                work_queue.get("work_pool_name", "null")
            ).set(state)


    def run_metrics_loop(self) -> None:
        """
        Metrics infinite loop

        """
        # check endpoint
        PrefectHealthz(
            url = self.url,
            headers = self.headers,
            max_retries = self.max_retries,
            logger = self.logger
        ).get_health_check()


        while True:
            # get metrics
            self.get_admin_metrics()
            self.get_deployments_metrics()
            self.get_flows_metrics()
            self.get_flow_runs_metrics()
            self.get_work_pools_metrics()
            self.get_work_queues_metrics()

            # wait
            time.sleep(self.polling_interval_seconds)
