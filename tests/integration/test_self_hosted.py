"""
The exporter against a real open-source Prefect server.

Run with a server started from compose.yml and
tests/integration/compose.override.yml:

    PREFECT_INTEGRATION_API_URL=http://localhost:4200/api pytest -m integration
"""

import logging
import time

import pytest
from prometheus_client import CollectorRegistry

from metrics.config import Config
from metrics.exporter import Exporter

# The server's backfill window, set in compose.override.yml.
SERVER_BACKFILL_SECONDS = 10.0
# The server's default event persister flush interval.
PERSISTER_FLUSH_SECONDS = 5.0

STREAM_TIMINGS = dict(
    ping_interval=1.0,
    ping_timeout=2.0,
    delivering_grace=1.0,
    backoff_initial=0.2,
    backoff_max=0.5,
    refusal_retry=1.0,
)


class Running:
    """An exporter running in this process, with its own registry."""

    def __init__(self, api_url, **stream_overrides):
        self.registry = CollectorRegistry()
        config = Config.from_env(
            {
                "PREFECT_API_URL": api_url,
                "INVENTORY_POLL_INTERVAL_SECONDS": "2",
                "RUN_POLL_INTERVAL_SECONDS": "5",
                "FAILED_RUNS_OFFSET_MINUTES": "0",
                "STREAM_BACKFILL_WINDOW_SECONDS": str(SERVER_BACKFILL_SECONDS),
            }
        )
        self.exporter = Exporter(
            config,
            self.registry,
            logging.getLogger("integration"),
            stream_settings_overrides={**STREAM_TIMINGS, **stream_overrides},
        )

    def value(self, name, **labels):
        return self.registry.get_sample_value(name, labels)

    def terminal(self, deployment, state_type, state_name):
        labels = {k: v for k, v in deployment.items() if k != "id"}
        return (
            self.value(
                "prefect_flow_runs_terminal_total",
                **labels,
                state_type=state_type,
                state_name=state_name,
            )
            or 0.0
        )

    def subscribed(self):
        return self.value("prefect_exporter_stream_connected") == 1

    def __enter__(self):
        self.exporter.start()
        wait_for(self.subscribed)
        return self

    def __exit__(self, *exc):
        self.exporter.stop()


def wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.1)


def test_counts_each_terminal_state_an_attempt_entered(api_url, prefect):
    deployment = prefect.deployment("states")
    with Running(api_url) as running:
        # The inventory creates the deployment's series at zero, with the
        # same labels the run events carry.
        wait_for(
            lambda: running.value(
                "prefect_flow_runs_terminal_total",
                **{k: v for k, v in deployment.items() if k != "id"},
                state_type="FAILED",
                state_name="TimedOut",
            )
            == 0
        )

        plans = [
            [("PENDING", None), ("RUNNING", None), ("COMPLETED", None)],
            [("RUNNING", None), ("COMPLETED", "Cached")],
            [("RUNNING", None), ("FAILED", "TimedOut")],
            [("RUNNING", None), ("CRASHED", None), ("CANCELLED", None)],
            [
                ("RUNNING", None),
                ("FAILED", None),
                ("SCHEDULED", None),
                ("RUNNING", None),
                ("COMPLETED", None),
            ],
            [
                ("RUNNING", None),
                ("SCHEDULED", "AwaitingRetry"),
                ("RUNNING", "Retrying"),
                ("COMPLETED", None),
            ],
            [("RUNNING", None), ("FAILED", "Exploded")],
            [("CANCELLING", None), ("CANCELLED", None)],
        ]
        for plan in plans:
            prefect.walk(prefect.run(deployment), *plan)

        expected = {
            ("COMPLETED", "Completed"): 3,
            ("COMPLETED", "Cached"): 1,
            ("FAILED", "Failed"): 1,
            ("FAILED", "TimedOut"): 1,
            ("FAILED", "Exploded"): 1,
            ("CRASHED", "Crashed"): 1,
            ("CANCELLED", "Cancelled"): 2,
        }
        wait_for(
            lambda: {key: running.terminal(deployment, *key) for key in expected}
            == expected
        )
        assert (
            running.value(
                "prefect_flow_run_duration_seconds_count",
                deployment_name=deployment["deployment_name"],
                flow_name=deployment["flow_name"],
                state_type="COMPLETED",
            )
            == 4
        )
        assert running.value("prefect_exporter_stream_gap_seconds_total") == 0


def test_a_short_disconnect_is_covered_by_backfill(api_url, prefect, relay):
    relay, relayed_url = relay
    deployment = prefect.deployment("short-cut")
    with Running(relayed_url) as running:
        relay.refuse()
        relay.cut()
        prefect.walk(prefect.run(deployment), ("RUNNING", None), ("COMPLETED", None))
        prefect.walk(prefect.run(deployment), ("RUNNING", None), ("FAILED", None))
        # Shorter than the backfill window, and long enough for the server
        # to write the events to its database before the reconnect.
        time.sleep(PERSISTER_FLUSH_SECONDS + 2)
        relay.refuse(False)

        wait_for(
            lambda: running.terminal(deployment, "COMPLETED", "Completed") == 1
            and running.terminal(deployment, "FAILED", "Failed") == 1
        )
        assert (
            running.value("prefect_exporter_stream_reconnects_total", reason="error")
            >= 1
        )
        assert running.value("prefect_exporter_stream_gap_seconds_total") == 0


def test_a_disconnect_longer_than_the_backfill_window_reports_its_gap(
    api_url, prefect, relay
):
    relay, relayed_url = relay
    deployment = prefect.deployment("long-cut")
    with Running(relayed_url) as running:
        relay.refuse()
        relay.cut()
        cut_at = time.monotonic()
        # Older than the backfill window at reconnect, so never replayed.
        prefect.walk(prefect.run(deployment), ("RUNNING", None), ("FAILED", None))
        time.sleep(4)
        # Inside the window at reconnect, so replayed. The server writes
        # events to its database every 5 seconds, and backfill reads only what
        # it has written, so this event is written before the reconnect.
        prefect.walk(prefect.run(deployment), ("RUNNING", None), ("COMPLETED", None))
        time.sleep(PERSISTER_FLUSH_SECONDS + 4)
        relay.refuse(False)

        wait_for(lambda: running.terminal(deployment, "COMPLETED", "Completed") == 1)
        outage = time.monotonic() - cut_at
        wait_for(
            lambda: (running.value("prefect_exporter_stream_gap_seconds_total") or 0)
            > 0
        )
        time.sleep(1)

        assert running.terminal(deployment, "FAILED", "Failed") == 0
        gap = running.value("prefect_exporter_stream_gap_seconds_total")
        assert gap == pytest.approx(outage - SERVER_BACKFILL_SECONDS, abs=2.5)


def test_a_restarted_exporter_does_not_count_the_previous_process_again(
    api_url, prefect
):
    deployment = prefect.deployment("restart")
    with Running(api_url) as first:
        prefect.walk(prefect.run(deployment), ("RUNNING", None), ("COMPLETED", None))
        wait_for(lambda: first.terminal(deployment, "COMPLETED", "Completed") == 1)

    # The first run's events are now in the server's database and inside its
    # backfill window, so a restart that asked for backfill would get them.
    time.sleep(PERSISTER_FLUSH_SECONDS + 1)
    with Running(api_url) as restarted:
        prefect.walk(prefect.run(deployment), ("RUNNING", None), ("COMPLETED", None))
        wait_for(
            lambda: (
                restarted.value(
                    "prefect_exporter_stream_events_total", outcome="counted"
                )
                or 0
            )
            >= 1
        )
        time.sleep(1)
        assert restarted.terminal(deployment, "COMPLETED", "Completed") == 1
