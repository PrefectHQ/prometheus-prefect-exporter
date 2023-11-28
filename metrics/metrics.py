from metrics.deployments import PrefectDeployments
from metrics.flow_runs import PrefectFlowRuns
from metrics.flows import PrefectFlows
from metrics.work_pools import PrefectWorkPools
from metrics.work_queues import PrefectWorkQueues
from prometheus_client.core import GaugeMetricFamily


class PrefectMetrics(object):
    """
    PrefectMetrics class for collecting and exposing Prometheus metrics related to Prefect.
    """

    def __init__(self, url, headers, offset_minutes, max_retries, logger) -> None:
        """
        Initialize the PrefectMetrics instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            offset_minutes (int): Time offset in minutes.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.

        """
        self.headers                  = headers
        self.offset_minutes           = offset_minutes
        self.url                      = url
        self.max_retries              = max_retries
        self.logger                   = logger


    def collect(self):
        """
        Get and set Prefect work queues metrics.

        """
        ##
        # PREFECT GET RESOURCES
        #
        deployments = PrefectDeployments(self.url, self.headers, self.max_retries, self.logger).get_deployments_info()
        flows = PrefectFlows(self.url, self.headers, self.max_retries, self.logger).get_flows_info()
        flow_runs = PrefectFlowRuns(self.url, self.headers, self.max_retries, self.offset_minutes, self.logger).get_flow_runs_info()
        work_pools = PrefectWorkPools(self.url, self.headers, self.max_retries, self.logger).get_work_pools_info()
        work_queues = PrefectWorkQueues(self.url, self.headers, self.max_retries, self.logger).get_work_queues_info()

        ##
        # PREFECT DEPLOYMENTS METRICS
        #

        # prefect_deployments metric
        prefect_deployments = GaugeMetricFamily("prefect_deployments_total", "Prefect total deployments", labels=[])
        prefect_deployments.add_metric([], len(deployments))
        yield prefect_deployments

        # prefect_info_deployments metric
        prefect_info_deployments = GaugeMetricFamily ("prefect_info_deployment", "Prefect deployment info",
                                              labels=[
                                                "created", "flow_id", "flow_name", "deployment_id", "is_schedule_active",
                                                "deployment_name", "path", "work_pool_name", "work_queue_name"
                                              ]
                                             )

        for deployment in deployments:
            # get flow name
            if deployment.get("flow_id") is None:
                flow_name = "null"
            else:
                flow_name = next((flow.get("name") for flow in flows if flow.get("id") == deployment.get("flow_id")), "null")

            prefect_info_deployments.add_metric(
                [
                  str(deployment.get("created", "null")),
                  str(deployment.get("flow_id", "null")),
                  str(flow_name),
                  str(deployment.get("id", "null")),
                  str(deployment.get("is_schedule_active", "null")),
                  str(deployment.get("name", "null")),
                  str(deployment.get("path", "null")),
                  str(deployment.get("work_pool_name", "null")),
                  str(deployment.get("work_queue_name", "null"))
                ], 1)

        yield prefect_info_deployments

        ##
        # PREFECT FLOWS METRICS
        #

        # prefect_flows metric
        prefect_flows = GaugeMetricFamily("prefect_flows_total", "Prefect total flows", labels=[])
        prefect_flows.add_metric([], len(flows))
        yield prefect_flows

        # prefect_info_flows metric
        prefect_info_flows = GaugeMetricFamily("prefect_info_flows", "Prefect flow info",
                                        labels=[
                                          "created", "flow_id", "flow_name"
                                        ]
                                       )

        for flow in flows:
            prefect_info_flows.add_metric(
              [
                str(flow.get("created", "null")),
                str(flow.get("id", "null")),
                str(flow.get("name", "null"))
              ], 1)

        yield prefect_info_flows

        ##
        # PREFECT FLOW RUNS METRICS
        #

        # prefect_flow_runs metric
        prefect_flow_runs = GaugeMetricFamily("prefect_flow_runs_total", "Prefect total flow runs", labels=[])
        prefect_flow_runs.add_metric([], len(flow_runs))
        yield prefect_flow_runs

        # prefect_flow_runs_total_run_time metric
        prefect_flow_runs_total_run_time = GaugeMetricFamily("prefect_flow_runs_total_run_time", "Prefect flow-run total run time in seconds", labels=[
                                          "flow_id", "flow_name", "flow_run_name"
                                        ]
                                      )

        for flow_run in flow_runs:
            # get deployment name
            if flow_run.get("deployment_id") is None:
                deployment_name = "null"
            else:
                deployment_name = next((deployment.get("name") for deployment in deployments if flow_run.get("deployment_id") == deployment.get("id")), "null")

            # get flow name
            if flow_run.get("flow_id") is None:
                flow_name = "null"
            else:
                flow_name = next((flow.get("name") for flow in flows if flow.get("id") == flow_run.get("flow_id")), "null")

            prefect_flow_runs_total_run_time.add_metric(
                [
                  str(flow_run.get("flow_id", "null")),
                  str(flow_name),
                  str(flow_run.get("name", "null"))
                ], str(flow_run.get("total_run_time", "null")))

        yield prefect_flow_runs_total_run_time

        # prefect_info_flow_runs metric
        prefect_info_flow_runs = GaugeMetricFamily("prefect_info_flow_runs", "Prefect flow runs info",
                                        labels=[
                                          "created", "deployment_id", "deployment_name", "end_time", "flow_id",
                                          "flow_name", "flow_run_id", "flow_run_name", "run_count", "start_time", "state_id",
                                          "state_name", "total_run_time", "work_queue_name"
                                        ]
                                       )

        for flow_run in flow_runs:
            # get deployment name
            if flow_run.get("deployment_id") is None:
                deployment_name = "null"
            else:
                deployment_name = next((deployment.get("name") for deployment in deployments if flow_run.get("deployment_id") == deployment.get("id")), "null")

            # get flow name
            if flow_run.get("flow_id") is None:
                flow_name = "null"
            else:
                flow_name = next((flow.get("name") for flow in flows if flow.get("id") == flow_run.get("flow_id")), "null")

            # set state
            state = 0 if flow_run.get("state_name") != "Running" else 1
            prefect_info_flow_runs.add_metric(
                [
                  str(flow_run.get("created", "null")),
                  str(flow_run.get("deployment_id", "null")),
                  str(deployment_name),
                  str(flow_run.get("end_time", "null")),
                  str(flow_run.get("flow_id", "null")),
                  str(flow_name),
                  str(flow_run.get("id", "null")),
                  str(flow_run.get("name", "null")),
                  str(flow_run.get("run_count", "null")),
                  str(flow_run.get("start_time", "null")),
                  str(flow_run.get("state_id", "null")),
                  str(flow_run.get("state_name", "null")),
                  str(flow_run.get("total_run_time", "null")),
                  str(flow_run.get("work_queue_name", "null"))
                ], state)

        yield prefect_info_flow_runs

        ##
        # PREFECT WORK POOLS METRICS
        #

        # prefect_work_pools metric
        prefect_work_pools = GaugeMetricFamily("prefect_work_pools_total", "Prefect total work pools", labels=[])
        prefect_work_pools.add_metric([], len(work_pools))
        yield prefect_work_pools

        # prefect_info_work_pools metric
        prefect_info_work_pools = GaugeMetricFamily("prefect_info_work_pools", "Prefect work pools info",
                                        labels=[
                                          "created", "work_queue_id", "work_pool_id", "is_paused",
                                          "work_pool_name", "type"
                                        ]
                                       )

        for work_pool in work_pools:
            state = 0 if work_pool.get("is_paused") else 1
            prefect_info_work_pools.add_metric(
                [
                  str(work_pool.get("created", "null")),
                  str(work_pool.get("default_queue_id", "null")),
                  str(work_pool.get("id", "null")),
                  str(work_pool.get("is_paused", "null")),
                  str(work_pool.get("name", "null")),
                  str(work_pool.get("type", "null"))
                ], state)

        yield prefect_info_work_pools

        ##
        # PREFECT WORK QUEUES METRICS
        #

        # prefect_work_queues metric
        prefect_work_queues = GaugeMetricFamily("prefect_work_queues_total", "Prefect total work queues", labels=[])
        prefect_work_queues.add_metric([], len(work_queues))
        yield prefect_work_queues

        # prefect_info_work_queues metric
        prefect_info_work_queues = GaugeMetricFamily("prefect_info_work_queues", "Prefect work queues info",
                                        labels=[
                                          "created", "work_queue_id", "is_paused", "work_queue_name", "priority",
                                          "type", "work_pool_id", "work_pool_name"
                                        ]
                                       )

        for work_queue in work_queues:
            state = 0 if work_queue.get("is_paused") else 1
            prefect_info_work_queues.add_metric(
                [
                 str(work_queue.get("created", "null")),
                 str(work_queue.get("id", "null")),
                 str(work_queue.get("is_paused", "null")),
                 str(work_queue.get("name", "null")),
                 str(work_queue.get("priority", "null")),
                 str(work_queue.get("type", "null")),
                 str(work_queue.get("work_pool_id", "null")),
                 str(work_queue.get("work_pool_name", "null"))
                ], state)

        yield prefect_info_work_queues
