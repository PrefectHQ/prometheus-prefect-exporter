# Migrating to version 5

Version 5 counts flow runs from the Prefect event stream instead of sampling their state on each
scrape. The sampled metrics missed every run that reached a terminal state between two scrapes, so
they undercounted. Three flow-run metrics are removed and replaced; nothing else is removed.

| Removed | Replaced by |
| --- | --- |
| `prefect_info_flow_runs` | `prefect_flow_runs_terminal_total` for runs that finished, `prefect_flow_runs_current` for runs that have not |
| `prefect_flow_runs_total` | `prefect_flow_runs_terminal_total` |
| `prefect_flow_runs_total_run_time` | `prefect_flow_run_duration_seconds` |

The new metrics are described in the [README](../README.md#metrics).

## Before you upgrade

- On Prefect Cloud, give the exporter's API key the `see_events` scope.
- Run one exporter per workspace or server: on Kubernetes, one replica with the `Recreate` strategy.
  Two exporters, or two pods during a rolling update, each count every run.
- Give the exporter's scrape target a stable `instance` label and drop the `pod` label, so a
  replaced pod continues the same series. The README has a scrape config.
- If you install with the Helm chart, upgrade to the chart release that pairs with exporter version
  5. It runs one replica with `Recreate` and sets the ServiceMonitor relabeling. An older chart does
  neither, so set them yourself or wait for that chart release.
- A self-hosted server with more than one API replica needs the Redis message broker.

## Replacement queries

Each panel of the shipped dashboards, `dashboards/prefect-platform-overview.json` and
`dashboards/prefect-flow-run-overview.json`, has been updated to the query on the right. Copy the
same change into dashboards you built from them. `$__range` and `$__rate_interval` are Grafana
variables; outside Grafana, use a range such as `[1h]`.

| Panel | Version 4 | Version 5 |
| --- | --- | --- |
| Flow Runs total (now Flow Runs finished) | `count(prefect_info_flow_runs)` | `sum(increase(prefect_flow_runs_terminal_total[$__range]))` |
| Flow Runs total, per flow (now Flow Runs finished) | `count(prefect_info_flow_runs{flow_name=~"$flow_name"})` | `sum(increase(prefect_flow_runs_terminal_total{flow_name=~"$flow_name"}[$__range]))` |
| Flow Runs running | `count(prefect_info_flow_runs == 1)` | `sum(prefect_flow_runs_current{state_type="RUNNING"})` |
| Flow Runs by state (now Flow Runs finished by state) | `count by (state_name) (prefect_info_flow_runs)` | `sum by (state_name) (increase(prefect_flow_runs_terminal_total[$__range]))` |
| Flow runs table | `prefect_info_flow_runs{state_name=~"$flow_run_state_name", flow_name=~"$flow_name"}` | `prefect_flow_runs_current{state_name=~"$flow_run_state_name", flow_name=~"$flow_name"}`, one row per deployment, flow, work queue and state, with the number of runs in the `runs` column |
| Flow Runs average run time | `avg(prefect_flow_runs_total_run_time)` | `sum(rate(prefect_flow_run_duration_seconds_sum[$__range])) / sum(rate(prefect_flow_run_duration_seconds_count[$__range]))` |
| Average time, per flow | `avg by (flow_name) (prefect_flow_runs_total_run_time{flow_name=~"$flow_name"})` | `sum by (flow_name) (rate(prefect_flow_run_duration_seconds_sum{flow_name=~"$flow_name"}[$__range])) / sum by (flow_name) (rate(prefect_flow_run_duration_seconds_count{flow_name=~"$flow_name"}[$__range]))` |
| Flow Run total run time (now Flow Run average run time) | `avg by (flow_name) (prefect_flow_runs_total_run_time{flow_name=~"$flow_name"})` | the per-flow average above, with `[$__rate_interval]` |
| `flow_run_state_name` variable | `label_values(prefect_info_flow_runs,state_name)` | `label_values(prefect_flow_runs_current,state_name)` |
| `flow_run_name` variable | `label_values(prefect_info_flow_runs{flow_name="$flow_name"},flow_run_name)` | `label_values(prefect_flow_runs_current{flow_name="$flow_name"},flow_run_name)` |

The Helm chart's example alert `PrefectFlowRunCrashedOrFailed`:

```yaml
# Version 4
expr: group by (flow_name, flow_run_name, namespace) (count_over_time(prefect_info_flow_runs{state_name=~"Failed|Crashed"}[1m]))
# Version 5
expr: sum by (flow_name, deployment_name, state_name, namespace) (increase(prefect_flow_runs_terminal_total{state_type=~"FAILED|CRASHED"}[5m])) > 0
```

The new alert no longer names the run, because the terminal counter has no per-run label.
`prefect_deployment_failed_flow_runs` still has `last_failed_run_id` for each deployment.

## Counts that differ from the Prefect UI

The terminal counter counts each terminal state a run attempt enters. A run that failed and then
completed after a manual retry counts once as failed and once as completed. The Prefect UI shows one
row per run in its current state, so it shows that run once, as completed.

The counter matches state types, so `state_type="FAILED"` includes runs whose state name is
`TimedOut` or a custom name. A run that retried inside its own process and then failed counts once,
as the last attempt's failure.

## Other changes

- `OFFSET_MINUTES` is no longer used; the exporter logs a warning if it is set.
- The exporter no longer exits at startup when the Prefect API is unreachable. It serves `/metrics`
  at once and keeps retrying, and `prefect_exporter_poll_success` and
  `prefect_exporter_stream_connected` show 0 until it connects.
- `prefect_flow_runs_ongoing_run_time` has a new `work_queue_name` label, and includes late
  scheduled runs, timed from their expected start time.
- On the new metrics, a run without a deployment has empty `deployment_name`, `work_pool_name` and
  `work_queue_name` labels. The inventory metrics still use `null` for a missing value.
- The image no longer installs the `prefect` package.
