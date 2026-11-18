# ADR: Count Flow-Run Terminal States From the Event Stream

## Status

Accepted

## Context

The exporter computes its flow-run metrics from what each run's state is when Prometheus scrapes.
`prefect_info_flow_runs` lists runs from a recent window and reports how many are in each state at
that moment. A run can pass through a terminal state between two scrapes and never be seen in it, so
completed, failed, crashed and cancelled counts built from these snapshots come out low. Users have
reported Grafana counts below the Prefect UI's for the same window. The loss grows with run length,
because the exporter lists only runs that started in the last few minutes. Run side by side on a
Prefect-operated workspace, version 4.2.0 reported 99.2% of terminal runs that took under a minute,
84% of runs that took 1 to 3 minutes, and 2 of 66 runs that took 3 to 10 minutes.

The same model makes scrapes expensive. Every scrape pages through `/flow_runs/filter`, and a page
that fails partway leaves the metrics short with no signal that anything went wrong.

Every flow-run state change already produces a Prefect event, and Prefect Cloud and Prefect Server
both stream events to API clients over the `/events/out` websocket.

## Decision

The exporter counts flow-run terminal states from the `/events/out` stream, in the exporter process.

- One subscription per exporter receives `prefect.flow-run.*` events, excluding heartbeats and
  pull-step events. Every nine minutes, before Prefect Cloud's connection time limit, the exporter
  opens a replacement subscription with replay beside the old one and closes the old one once the
  new one delivers; the record of counted pairs below absorbs the overlap. After three replays in a
  row fail, it connects once without replay.
- A state is terminal by its state type: `COMPLETED`, `FAILED`, `CRASHED` or `CANCELLED`.
- A run attempt is the run id plus the run count in its events. Each terminal state an attempt
  enters adds one to that state's counter, once. An attempt that reports `CRASHED` and then
  `CANCELLED` counts in both.
- The exporter remembers the (attempt, state type) pairs it has counted for 24 hours, so redelivered
  and duplicate events count once.
- On reconnecting within one process it asks the server to replay recent events; on its first
  connection after starting it does not, because Prometheus has already credited the previous
  process's counts.
- Counts are exposed as `prefect_flow_runs_terminal_total`, labelled `deployment_name`, `flow_name`,
  `work_pool_name`, `work_queue_name`, `state_type` and `state_name`, plus a run-duration histogram.
  Counter series for every known deployment and standard state name are created at zero, so once
  Prometheus has scraped the zero, the next count is visible to `increase()`. The exporter also
  exposes each series' created timestamp, which Prometheus can use in place of a scraped zero when
  it ingests created timestamps.
- Current state (runs scheduled, pending, running, paused or cancelling now), the ongoing-run gauge,
  recent failed runs and the inventory metrics stay polled, on background loops rather than inside
  the scrape.
- Exactly one exporter runs per workspace or server, deployed with the `Recreate` strategy.

`prefect_info_flow_runs`, `prefect_flow_runs_total` and `prefect_flow_runs_total_run_time` are
removed in the same major version, with no transition period.

## Rationale

### Why the event stream

A state change is an event the server already emits once per change. Counting events counts every
transition, including the ones that start and end between scrapes, which no amount of faster or
cheaper polling can do. It also removes the run listing from the scrape: the scrape reads counters
the stream has already updated.

### Why every terminal state an attempt enters

A Prometheus counter can only go up. Counting each terminal state an attempt enters keeps every
per-state counter exact and monotonic. The alternative, counting only the first terminal state,
misreports the later state for about 2.3% of crashed attempts and 0.16% of cancelled ones, because a
crash is often followed by the attempt's real outcome. The cost is that the sum across states
exceeds the number of attempts by about 0.03%.

### Why one exporter per workspace or server

Each exporter counts the whole stream on its own. Two exporters produce two independent counts that
no query combines correctly: summing doubles them, and taking the maximum undercounts whenever the
two missed different stretches. `Recreate` avoids the moment a rolling update runs an old and a new
exporter side by side, when both would count the same events.

### Why keep every label

Dashboards and alerts filter on deployment, flow, work queue and state name today. The new counter
keeps those labels so they can be ported query by query, and adds `state_type` and `work_pool_name`.

## Alternatives Considered

- **Keep sampling state at scrape time, with cheaper queries.** Rejected: it makes scrapes faster
  and leaves the undercount, which is the defect.
- **Count only the first terminal state of each attempt.** Rejected: a counter cannot be corrected
  when a later terminal state arrives, so the first state's count is wrong for crashed and cancelled
  attempts, which are the counts users alert on.
- **Have the Prefect server keep the totals and the exporter poll them.** Rejected: it needs new
  server-side code, gives Prefect Server users nothing unless it is built twice, delays counts by
  minutes, and a server total that ever reads lower than the last scrape becomes a counter reset in
  Prometheus, which reports the whole total as new.
- **Deduplicate by event id.** Rejected: duplicate terminal events have distinct ids. On the same
  workspace, 1,794 failed-state events belonged to 1,571 failed attempts, so counting by event id
  would report 14% more failures than happened.
- **Persist a cursor and catch up through a server query after any disconnect.** Rejected for now:
  exact through long disconnects, at the cost of a store and volume for every exporter and a new
  server query. Exporter downtime is rare enough that the loss it prevents is small.
- **Run more than one exporter per workspace or server for high availability.** Rejected: see "Why
  one exporter per workspace or server".

## Consequences

### Positive

- Flow-run terminal counts no longer depend on scrape timing or run length. A terminal state that
  reaches the exporter is counted once, as long as any duplicate copy arrives within 24 hours.
  Counts on a series that was not created at zero, made before Prometheus first scrapes it, are not
  visible to `increase()` (see Negative). The target is counts within 0.1% of a recount of the same
  events. Over 18.6 hours on a Prefect-operated workspace, through 24 unplanned disconnects, the
  counter matched a recount of the same events in every state (30,416 terminal runs).
- Scrapes read stored values, so a slow or failing Prefect API cannot fail `/metrics`, and scrape
  cost no longer grows with the number of runs.
- The exporter reports its own collection health: whether it is connected, how long it was
  disconnected beyond what replay covers, failed replays, and polling errors by endpoint.

### Negative

- Terminal states that happen while the exporter is down are never counted. Under the rejected
  server-held totals they would have been recovered once the exporter came back. The loss is bounded
  by the exporter's downtime, and the exporter's process start time shows when it happened;
  operators who need complete totals alert on the exporter's `up`.
- A disconnection longer than the server's replay window loses the events in between. The exporter
  reports that time, and nothing recovers it.
- Some losses are invisible to the exporter: an event the server drops while the socket stays open,
  one that arrives late enough to fall outside the replay window, or, on Prefect Server, an event
  from the few seconds before an unplanned reconnect that the server had not yet written to its
  database (5 seconds by default). They are small, and they are the reason the target is within 0.1%
  of a recount rather than exact.
- Counts made between an exporter start and Prometheus's first scrape of it are not visible to
  `increase()`: a new series' first sample is already above zero, and after a restart the new
  process's counter may pass the old one's last value before a decrease is ever scraped, so the
  reset goes undetected. The loss is bounded by one scrape interval per start, unless Prometheus
  ingests created timestamps.
- A series the exporter did not create in advance (a run on a non-default work queue, a custom state
  name) loses every count made before Prometheus first scrapes it after each exporter start, unless
  Prometheus ingests created timestamps.
- The API key needs permission to read events, which the previous exporter did not. On Prefect
  Server, the outbound event stream must be enabled (it is by default); with it turned off the
  exporter produces no terminal counts, and it reports this through its refused gauge.
- Upgrading removes three metrics. Dashboards and alerts that use them stop returning data until
  they are rewritten, and an alert on a removed metric stops firing.
- The per-state counts differ by definition from the Prefect UI, which counts each run once in its
  current state. A run that failed and then completed after a retry counts once in each state here.

## When to revisit

- If exporter downtime becomes common or long for users who need exact totals, a persisted cursor
  and a server catch-up query become worth their cost.
- If the server stops replaying recent events on connect, or shortens how long a websocket may stay
  open below a few minutes, the reconnect design needs another look.
- If Prefect adds other high-volume event types under `prefect.flow-run.*`, the subscription filter
  needs updating.

## References

- Implemented by: [PrefectHQ/prometheus-prefect-exporter#186](https://github.com/PrefectHQ/prometheus-prefect-exporter/pull/186)
- Chart change it depends on: [PrefectHQ/prefect-helm#700](https://github.com/PrefectHQ/prefect-helm/pull/700)
