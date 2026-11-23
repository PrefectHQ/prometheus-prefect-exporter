# Prometheus Prefect Exporter

A Prometheus exporter for [Prefect](https://www.prefect.io/) metrics, written in Python. Originally contributed by @ialejandro!

## Usage

By default `prometheus-prefect-exporter` will listen on port `8000`.

A scrape reads values the exporter has already stored and sends no request to the Prefect API, so any
scrape interval works. The exporter reads Prefect on its own schedule:

- Flow-run terminal states (completed, failed, crashed, cancelled) arrive as they happen, from the
  Prefect event stream (`/events/out`), and are counted in `prefect_flow_runs_terminal_total`.
- Runs that have not finished are polled every 60 seconds (`RUN_POLL_INTERVAL_SECONDS`).
- Deployments, flows, work pools, work queues and recent failed runs are polled every 5 minutes
  (`INVENTORY_POLL_INTERVAL_SECONDS`).

Upgrading from version 4? Read the [migration note](./docs/migrating-to-5.md): three flow-run metrics
were replaced.

### Requirements

- **Run exactly one exporter per Prefect workspace or server.** Each exporter counts the events it
  receives, so two exporters each count every run, and no query combines them correctly. A
  Kubernetes Deployment of the exporter needs one replica and the `Recreate` strategy, because the
  default `RollingUpdate` runs the old and new pods together and both count the overlap. Set
  `replicas: 1` and `strategy: {type: Recreate}` on the Deployment. The Helm chart sets both from the
  chart release that pairs with exporter version 5; on an older chart, set them yourself.
- **The API key needs the `see_events` scope** on Prefect Cloud, to read the event stream.
- **Give the exporter a stable `instance` label.** A replaced exporter pod is otherwise a new series,
  and `increase()` reads each series' first count as zero. Set `instance` to a fixed value and drop
  the `pod` label. The Helm chart's ServiceMonitor does this from the chart release that pairs with
  exporter version 5; with an older chart, add the two rules to `serviceMonitor.relabelings`. For a
  hand-written scrape config:

  ```yaml
  scrape_configs:
    - job_name: prefect
      static_configs:
        - targets: ["prometheus-prefect-exporter:8000"]
      relabel_configs:
        - target_label: instance
          replacement: prometheus-prefect-exporter
  ```
- **A self-hosted Prefect server with more than one API replica needs the Redis message broker**
  (`prefect-redis`). With the default in-memory broker, the event stream only sends the events
  published on the replica the exporter's socket reached.

### What the counts include and miss

`prefect_flow_runs_terminal_total` counts each terminal state a flow run attempt enters, once. An
attempt is a flow run and its run count, which Prefect raises each time the run enters `Running`. A
run that failed and then completed after a manual retry counts once in each state. The Prefect UI
shows one row per run in its current state instead, so its numbers differ.

The exporter reports what it can see of its own completeness:

- `prefect_exporter_stream_gap_seconds_total` counts the time in which terminal states may be
  missing: the part of an outage that the server's replay on reconnect did not cover (it replays 2
  minutes on Prefect Cloud, 15 on a self-hosted server). It is not a part of the disconnected time:
  a reconnect that drops before it delivers ends the disconnected time but replays nothing, so the
  gap can be longer.
- `prefect_exporter_stream_refused` is 1 while the server refuses the subscription, or while a
  self-hosted server has its outbound event stream disabled.
- A restarted exporter starts its counters at zero and does not replay earlier events, so nothing is
  counted twice; runs that ended while it was down are not counted, nor are counts the previous
  process made after Prometheus last scraped it.

To be told when counts may be incomplete, alert on these as well as `up`, which can stay at 1
through a restart between two scrapes or while the event subscription is disconnected:

- `prefect_exporter_stream_connected == 0` held for a few minutes (`for: 5m`): the subscription is
  down now. The gap metric below only grows once a later subscription delivers.
- `changes(process_start_time_seconds{job="<exporter job>"}[1h]) > 0`: the exporter restarted.
- `increase(prefect_exporter_stream_gap_seconds_total[1h]) > 0`: an outage outlasted the replay.
- `prefect_exporter_stream_refused == 1`: the server refuses the subscription.

It cannot see these losses:

- A self-hosted server drops events silently when an exporter's socket falls 256 events behind.
- A self-hosted server writes events to its database every 5 seconds by default, and replays only
  what it has written, so events in the last few seconds before an unplanned reconnect can be missed.
- A copy of a terminal event that arrives more than `DUPLICATE_MEMORY_HOURS` after the first copy, or
  after a restart, counts again.
- Counts on a series that Prometheus has not yet scraped at zero are not visible to `increase()`,
  because the series' first sample is already above zero. This can happen whenever such a series
  first appears: a custom state name, a run on a work queue other than its deployment's default, a
  flow run without a deployment when the flow has one, a deployment or flow created since the last
  inventory poll, or any count before the first inventory poll after a start.
- After a restart, if the new counter reaches the old process's last value before Prometheus scrapes
  it, `increase()` reads it as growth from the old value and misses that many counts. This can happen
  only before the first successful scrape after a start.
- On Prefect Cloud, a replay returns at most about 5,500 events. The limit applies to the events the
  exporter subscribes to, which are finished-state and RUNNING-type flow-run events (deleted,
  pre-run and paused events are not subscribed to), so a workspace loses events after an unplanned
  reconnect only if more than that many of those happen in the 2-minute replay window.
- The subscription leaves out events by name: deleted, and the state names Scheduled, Late,
  AwaitingRetry, AwaitingConcurrencySlot, Pending, Submitting, InfrastructurePending, Paused and
  Suspended. A finished state given one of those names is not counted, and a running state given one
  gives no start time for the duration on a self-hosted server.
- On a self-hosted server, a state-change event can be published before its database transaction
  commits ([PrefectHQ/prefect#22654](https://github.com/PrefectHQ/prefect/issues/22654)); if the
  transaction rolls back, the exporter counts a transition that never happened.

The exporter exposes created timestamps (`_created` series), so a Prometheus that ingests them for
this scrape format can avoid the two `increase()` losses above; check your Prometheus version and
scrape settings.

`state_name` is text that flow code can set, so its number of values, and the counter's number of
series, depends on your flows.

### Installing released versions

**Docker**

Pin a release tag. `latest` moves to each new major version, whose metrics can change.

```bash
docker run -d \
  -p 8000:8000 \
  -e PREFECT_API_URL=<PREFECT_ENDPOINT> \
  prefecthq/prometheus-prefect-exporter:<VERSION>
```

**Helm**

```bash
helm repo add prefect https://prefecthq.github.io/prefect-helm
helm search repo prefect
helm install prometheus-prefect-exporter prefect/prometheus-prefect-exporter
```

### Installing development versions

You will need to have a Prefect Server up and running for the exporter to communicate with. Follow these steps to set one up, or skip to step 3.

1. Install Prefect Server

```bash
helm repo add prefect https://prefecthq.github.io/prefect-helm
helm search repo prefect
helm install prefect-server prefect/prefect-server
```

2. Port forward the api to your localhost:

```bash
kubectl port-forward svc/prefect-server 4200:4200
```

3. Clone repository

```bash
git clone https://github.com/PrefectHQ/prometheus-prefect-exporter.git
```

4. Change to this directory

```bash
cd prometheus-prefect-exporter`
```

5. Setup a virtual environment of your choice & install dependencies

```bash
virtualenv prom-exporter
source prom-exporter/bin/activate
pip install -r requirements.txt
python main.py
```

#### Using Docker Compose

Alternatively, you can use the [Docker Compose configuration](./compose.yml)
to stand up the exporter alongside Prefect and Prometheus.

To get started, run:

```bash
docker compose up -d
```

Confirm the services are running and healthy:

```
docker compose ps
```

You can now reach each service locally:

- Prefect: http://localhost:4200
- Exporter: http://localhost:8000
- Prometheus: http://localhost:9090

## Configuration

You can modify environment variables to change the behavior of the exporter.
- An API Key is only required for auth-enabled, on-prem, self-managed solutions.
- An API key is not required for open-source or Prefect Server.
- If an API key and API auth string are provided, then the API key takes precedence.

| Environment Variable | Description | Default |
| --- | --- | --- |
| `LOG_LEVEL` | Logging level | `INFO` |
| `MAX_RETRIES` | Number of retries to attempt when fetching metrics from Prefect API | `3` |
| `METRICS_ADDR` | Address to expose metrics on | `0.0.0.0` |
| `METRICS_PORT` | Port to expose metrics on | `8000` |
| `PREFECT_API_URL` | Prefect API URL | `http://localhost:4200/api` |
| `PREFECT_API_KEY` | Prefect API key (Optional) | `""` |
| `PREFECT_API_AUTH_STRING` | Prefect API auth string, automatically base64-encoded (Optional) | `""` |
| `PREFECT_CSRF_ENABLED` | Enable compatibilty with Prefect Servers using CSRF protection | `False` |
| `PAGINATION_ENABLED` | Enable pagination for API requests. Can help reduce server load and avoid timeouts. Can be disabled on very small instances. | `True` |
| `PAGINATION_LIMIT` | Number of results to retrieve per request when pagination is enabled. Consider lowering this value for large instances to make more, but smaller, requests. | `200` |
| `FAILED_RUNS_OFFSET_MINUTES` | Time window in minutes for the `prefect_deployment_failed_flow_runs` metric, read on the inventory poll. Failed runs older than this window are ignored. Set to `0` to disable the metric entirely. | `10080` (7 days) |
| `FAILED_RUNS_LIMIT` | Maximum number of recent failed runs to expose per deployment in `prefect_deployment_failed_flow_runs`. | `10` |
| `ENABLE_FLOW_RUN_NAME_LABEL` | Add `flow_run_name` label to `prefect_flow_runs_current` and `prefect_flow_runs_ongoing_run_time`. Increases cardinality in proportion to the number of runs that have not finished. Note: `prefect_flow_runs_ongoing_run_time` always has a `flow_run_id` label so each ongoing run is a distinct series. | `False` |
| `INVENTORY_POLL_INTERVAL_SECONDS` | Seconds between polls of deployments, flows, work pools, work queues and recent failed runs. | `300` |
| `RUN_POLL_INTERVAL_SECONDS` | Seconds between polls of the runs that have not finished. | `60` |
| `DUPLICATE_MEMORY_HOURS` | How long a counted terminal state is remembered, so later copies of its event are not counted again. | `24` |
| `STREAM_BACKFILL_WINDOW_SECONDS` | The longest replay the server gives on reconnect, used to compute `prefect_exporter_stream_gap_seconds_total`. Set it if your server's `PREFECT_SERVER_EVENTS_MAXIMUM_WEBSOCKET_BACKFILL` is not the default. | `120` on Prefect Cloud, `900` otherwise |
| `REQUEST_TIMEOUT_SECONDS` | Timeout in seconds for connecting to the Prefect API and for each read from it. Timed-out requests are retried up to `MAX_RETRIES`. | `60` |

## Metrics

Flow runs:

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `prefect_flow_runs_terminal_total` | counter | `deployment_name`, `flow_name`, `work_pool_name`, `work_queue_name`, `state_type`, `state_name` | Terminal states entered by flow run attempts, each counted once per attempt and state type. Series for each deployment and its common state names exist at zero from the first inventory poll. |
| `prefect_flow_run_duration_seconds` | histogram | `deployment_name`, `flow_name`, `state_type` | Time an attempt spent running before its terminal state, for attempts that left `Running`. |
| `prefect_flow_runs_current` | gauge | `deployment_name`, `flow_name`, `work_queue_name`, `state_type`, `state_name` (`flow_run_name`) | Runs in each state that has not finished. Scheduled runs count once their expected start time has passed. |
| `prefect_flow_runs_ongoing_run_time` | gauge | `deployment_name`, `flow_name`, `state_name`, `flow_run_id`, `work_queue_name` (`flow_run_name`) | Seconds since each running, pending or late run started, or was expected to start. |
| `prefect_deployment_failed_flow_runs` | gauge | `deployment_name`, `flow_name`, `last_failed_run_id`, `state_name` | The most recent failed or crashed runs of each deployment. |

The inventory metrics (`prefect_deployments_total`, `prefect_info_deployment`, `prefect_flows_total`,
`prefect_info_flows`, `prefect_work_pools_total`, `prefect_info_work_pools`, `prefect_work_queues_total`,
`prefect_info_work_queues` and `prefect_work_queues_late_runs_count`) keep their names and labels.

The exporter's health:

| Metric | Type | Meaning |
| --- | --- | --- |
| `prefect_exporter_stream_connected` | gauge | 1 while the event stream socket is open and answering pings |
| `prefect_exporter_stream_refused` | gauge | 1 while the server refuses the subscription or has its event stream disabled |
| `prefect_exporter_stream_last_event_timestamp_seconds` | gauge | When the last event arrived |
| `prefect_exporter_stream_reconnects_total` | counter | Reconnects, by `reason` (`server_close`, `ping_timeout`, `error`) |
| `prefect_exporter_stream_disconnected_seconds_total` | counter | Time without a subscription |
| `prefect_exporter_stream_gap_seconds_total` | counter | Time in which terminal states may be missing because no replay covered it |
| `prefect_exporter_stream_backfill_failures_total` | counter | Connects that the server closed while replaying events |
| `prefect_exporter_stream_events_total` | counter | Events, by `outcome` (`counted`, `duplicate`, `ignored`, `malformed`); `missing_run_count` is counted in addition to an event's outcome |
| `prefect_exporter_poll_success` | gauge | 1 if the last poll of each `poller` read everything it asked for |
| `prefect_exporter_poll_duration_seconds` | histogram | Poll duration, by `poller` |
| `prefect_exporter_api_errors_total` | counter | Failed API requests, by `endpoint` and `status` |
| `prefect_exporter_poll_truncated_total` | counter | Listings whose pagination stopped before the last page, by `endpoint` |

The socket cannot tell a stalled stream from a quiet workspace: the server sends nothing while there
are no events.

## Contributing

Contributions to the Prometheus Prefect Exporter are always welcome. Fork this repository and commit changes to your local repository. You can then open a pull request against this upstream repository that the team will review.

To get started, ensure you have the required dependencies installed:

```shell
mise install
```

Be sure to run `pre-commit install` before starting any development. [`pre-commit`](https://pre-commit.com/)
will help catch simple issues before committing.

`pytest` runs the unit tests. The integration tests run the exporter against a Prefect server:

```shell
docker compose -f compose.yml -f tests/integration/compose.override.yml up -d --wait prefect
PREFECT_INTEGRATION_API_URL=http://localhost:4200/api pytest -m integration
```

`tests/integration/compose.ha.yml` starts two API replicas on the Redis broker instead; point
`PREFECT_INTEGRATION_API_URL` at `http://localhost:4280/api`.

### Releasing

Run the Release workflow from the Actions tab, or with
`gh workflow run cut-release.yaml -R PrefectHQ/prometheus-prefect-exporter -f bump=minor`.
It computes the next version from the highest version tag, runs the tests, pushes the image,
creates the GitHub release with generated notes, and then triggers the Helm chart release.
The tests are the full suite, including the integration job against two API
replicas on Redis. Label a pull request `breaking` when it needs a major release, so the release
notes group it with the other breaking changes. If a job fails, use "Re-run failed jobs" on that
run; "Re-run all jobs" and a new dispatch both refuse a commit that is already released.
The Release workflow is the only way to publish an image or a Helm chart: pushing a tag or
creating a release by hand in the GitHub UI publishes neither.

### Documentation

Please make sure that your changes have been linted and the documentation has been updated. The easiest way to accomplish this is by installing [`pre-commit`](https://pre-commit.com/).

### Opening a pull request

A helpful pull request explains _what_ changed and _why_ the change is important. Please take time to make your pull request descriptions as helpful as possible.

For pull requests from a fork, please follow [the GitHub instructions](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/allowing-changes-to-a-pull-request-branch-created-from-a-fork) to allow maintainers to push commits to your branch.
