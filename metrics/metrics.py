import time

from prometheus_client import Gauge, Info, Enum, generate_latest
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


    def __init__(self, url, headers, offset_minutes, polling_interval_seconds, registry, max_retries, logger) -> None:
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
        self.registry                 = registry
        self.max_retries              = max_retries
        self.logger                   = logger

        # Prefect admin metrics
        self.prefect_info_admin = Info("prefect_info_admin", "Prefect admin info", registry=self.registry)

        # Prefect deployments metrics
        self.prefect_deployments = Gauge("prefect_deployments_total", "Prefect total deployments", registry=self.registry)
        self.prefect_info_deployments = Gauge("prefect_info_deployment", "Prefect deployment info",
                                              [
                                                "created", "flow_id", "deployment_id", "is_schedule_active",
                                                "name", "path", "updated", "work_pool_name",
                                                "work_queue_name"
                                              ], registry=self.registry
                                             )

        # Prefect flows metrics
        self.prefect_flows = Gauge("prefect_flows_total", "Prefect total flows", registry=self.registry)
        self.prefect_info_flows = Gauge("prefect_info_flows", "Prefect flow info",
                                        [
                                          "created", "flow_id", "name", "updated"
                                        ], registry=self.registry
                                       )

        # Prefect flow_runs metrics
        self.prefect_flow_runs = Gauge("prefect_flow_runs_total", "Prefect total flow runs", registry=self.registry)
        self.prefect_info_flow_runs = Enum("prefect_info_flow_runs", "Prefect flow runs info",
                                        [
                                          "created", "deployment_id", "end_time", "flow_id",
                                          "flow_run_id", "name", "run_count", "start_time", "state_id",
                                          "total_run_time", "updated", "work_queue_name"
                                        ],
                                        states=[
                                            'Completed', 'Cancelled', 'Failed', 'Running',
                                            'Scheduled', 'Pending', 'Crashed', 'Cancelling', 'Paused',
                                            'TimedOut'
                                        ], registry=self.registry
                                       )

        # Prefect work_pools metrics
        self.prefect_work_pools = Gauge("prefect_work_pools_total", "Prefect total work pools", registry=self.registry)
        self.prefect_info_work_pools = Gauge("prefect_info_work_pools", "Prefect work pools info",
                                        [
                                          "created", "work_queue_id", "work_pool_id", "is_paused",
                                          "work_pool_name", "type", "updated"
                                        ], registry=self.registry
                                       )

        # Prefect work_queues metrics
        self.prefect_work_queues = Gauge("prefect_work_queues_total", "Prefect total work queues", registry=self.registry)
        self.prefect_info_work_queues = Gauge("prefect_info_work_queues", "Prefect work queues info",
                                        [
                                          "created", "work_queue_id", "is_paused", "work_queue_name", "priority",
                                          "type", "work_pool_id", "work_pool_name"
                                        ], registry=self.registry
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
            self.prefect_info_deployments.labels(
                deployment.get("created", "null"),
                deployment.get("flow_id", "null"),
                deployment.get("id", "null"),
                deployment.get("is_schedule_active", "null"),
                deployment.get("name", "null"),
                deployment.get("path", "null"),
                deployment.get("updated", "null"),
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
              flow.get("name", "null"),
              flow.get("updated", "null")
            ).set(1)


    def get_flow_runs_metrics(self) -> None:
        """
        Get and set Prefect flow runs metrics.

        """
        flow_runs = PrefectFlowRuns(self.url, self.headers, self.max_retries, self.offset_minutes, self.logger)

        # set flows metrics
        #flow_runs.get_flow_runs_history()
        self.prefect_flow_runs.set(flow_runs.get_flow_runs_count())
        for flow_run in flow_runs.get_flow_runs_info():
            self.prefect_info_flow_runs.labels(
                flow_run.get("created", "null"),
                flow_run.get("deployment_id", "null"),
                flow_run.get("end_time", "null"),
                flow_run.get("flow_id", "null"),
                flow_run.get("id", "null"),
                flow_run.get("name", "null"),
                flow_run.get("run_count", "null"),
                flow_run.get("start_time", "null"),
                flow_run.get("state_id", "null"),
                flow_run.get("total_run_time", "null"),
                flow_run.get("updated", "null"),
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
            self.prefect_info_work_pools.labels(
                work_pool.get("created", "null"),
                work_pool.get("default_queue_id", "null"),
                work_pool.get("id", "null"),
                work_pool.get("is_paused", "null"),
                work_pool.get("name", "null"),
                work_pool.get("type", "null"),
                work_pool.get("updated", "null")
            ).set(1)


    def get_work_queues_metrics(self) -> None:
        """
        Get and set Prefect work queues metrics.

        """
        work_queues = PrefectWorkQueues(self.url, self.headers, self.max_retries, self.logger)

        # set work_queues metrics
        self.prefect_work_queues.set(len(work_queues.get_work_queues_info()))
        for work_queue in work_queues.get_work_queues_info():
            self.prefect_info_work_queues.labels(
                work_queue.get("created", "null"),
                work_queue.get("id", "null"),
                work_queue.get("is_paused", "null"),
                work_queue.get("name", "null"),
                work_queue.get("priority", "null"),
                work_queue.get("type", "null"),
                work_queue.get("work_pool_id", "null"),
                work_queue.get("work_pool_name", "null")
            ).set(1)


    def run_metrics_loop(self) -> None:
        """
        Metrics fetching loop

        """
        while True:
            # check endpoint
            PrefectHealthz(
                url = self.url,
                headers = self.headers,
                max_retries = self.max_retries,
                logger = self.logger
            ).get_health_check()

            # get metrics
            self.get_admin_metrics()
            self.get_deployments_metrics()
            self.get_flows_metrics()
            self.get_flow_runs_metrics()
            self.get_work_pools_metrics()
            self.get_work_queues_metrics()

            # wait
            time.sleep(self.polling_interval_seconds)
