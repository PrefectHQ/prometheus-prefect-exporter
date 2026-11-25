import logging
import threading
import time

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily

from metrics.collector import PolledMetricsCollector
from metrics.health import ExporterHealth
from metrics.poller import PollLoop, PollResult

LOGGER = logging.getLogger("test")


def _family(value):
    family = GaugeMetricFamily("prefect_test_value", "test", labels=[])
    family.add_metric([], value)
    return family


def _loop(poll, registry, clock=time.monotonic, interval=60.0):
    health = ExporterHealth(registry)
    return PollLoop(
        "runs", poll, interval, health, threading.Event(), LOGGER, clock=clock
    )


def _value(registry, name, **labels):
    return registry.get_sample_value(name, labels)


def test_scrape_answers_while_a_poll_is_blocked():
    registry = CollectorRegistry()
    release = threading.Event()

    def blocked_poll():
        release.wait(10)
        return PollResult((_family(1),), True)

    loop = _loop(blocked_poll, registry)
    registry.register(PolledMetricsCollector([loop]))
    loop.start()
    try:
        started = time.monotonic()
        body = generate_latest(registry).decode()
        elapsed = time.monotonic() - started
    finally:
        release.set()
        loop.stop.set()
        loop.join(5)

    assert elapsed < 1
    assert 'prefect_exporter_poll_success{poller="runs"} 0.0' in body
    assert "prefect_test_value" not in body


def test_complete_poll_publishes_and_reports_success():
    registry = CollectorRegistry()
    loop = _loop(lambda: PollResult((_family(7),), True), registry)
    registry.register(PolledMetricsCollector([loop]))

    loop.poll_once()

    assert _value(registry, "prefect_test_value") == 7
    assert _value(registry, "prefect_exporter_poll_success", poller="runs") == 1
    assert (
        _value(registry, "prefect_exporter_poll_duration_seconds_count", poller="runs")
        == 1
    )


def _record_value_at_each_success_set(loop, registry, monkeypatch):
    gauge = loop.health.poll_success.labels("runs")
    original = gauge.set
    recorded = []

    def record_then_set(success):
        recorded.append((success, _value(registry, "prefect_test_value")))
        original(success)

    monkeypatch.setattr(gauge, "set", record_then_set)
    return recorded


def test_complete_result_is_published_before_success_is_reported(monkeypatch):
    registry = CollectorRegistry()
    results = iter([PollResult((_family(7),), True), PollResult((_family(8),), True)])
    loop = _loop(lambda: next(results), registry)
    registry.register(PolledMetricsCollector([loop]))
    recorded = _record_value_at_each_success_set(loop, registry, monkeypatch)

    loop.poll_once()
    loop.poll_once()

    assert recorded == [(1, 7), (1, 8)]


def test_partial_result_is_published_after_failure_is_reported(monkeypatch):
    registry = CollectorRegistry()
    now = [0.0]
    results = iter([PollResult((_family(7),), True), PollResult((_family(3),), False)])
    loop = _loop(lambda: next(results), registry, clock=lambda: now[0], interval=60)
    registry.register(PolledMetricsCollector([loop]))
    loop.poll_once()
    recorded = _record_value_at_each_success_set(loop, registry, monkeypatch)
    now[0] = 181.0

    loop.poll_once()

    assert recorded == [(0, 7)]
    assert _value(registry, "prefect_test_value") == 3


def test_poll_that_raises_after_a_good_one_reports_failure_and_keeps_its_snapshot(
    monkeypatch,
):
    registry = CollectorRegistry()
    results = iter([PollResult((_family(7),), True)])
    # The second call raises StopIteration.
    loop = _loop(lambda: next(results), registry)
    registry.register(PolledMetricsCollector([loop]))
    loop.poll_once()
    recorded = _record_value_at_each_success_set(loop, registry, monkeypatch)

    loop.poll_once()

    assert recorded == [(0, 7)]
    assert _value(registry, "prefect_exporter_poll_success", poller="runs") == 0
    assert _value(registry, "prefect_test_value") == 7


def test_poll_that_lost_data_keeps_the_previous_snapshot():
    registry = CollectorRegistry()
    results = iter([PollResult((_family(7),), True), PollResult((_family(3),), False)])
    loop = _loop(lambda: next(results), registry)
    registry.register(PolledMetricsCollector([loop]))

    loop.poll_once()
    loop.poll_once()

    assert _value(registry, "prefect_test_value") == 7
    assert _value(registry, "prefect_exporter_poll_success", poller="runs") == 0


def test_partial_result_replaces_a_snapshot_older_than_three_intervals():
    registry = CollectorRegistry()
    now = [0.0]
    results = iter([PollResult((_family(7),), True), PollResult((_family(3),), False)])
    loop = _loop(lambda: next(results), registry, clock=lambda: now[0], interval=60)
    registry.register(PolledMetricsCollector([loop]))

    loop.poll_once()
    now[0] = 181.0
    loop.poll_once()

    assert _value(registry, "prefect_test_value") == 3


def test_first_partial_result_is_published():
    registry = CollectorRegistry()
    loop = _loop(lambda: PollResult((_family(3),), False), registry)
    registry.register(PolledMetricsCollector([loop]))

    loop.poll_once()

    assert _value(registry, "prefect_test_value") == 3
    assert _value(registry, "prefect_exporter_poll_success", poller="runs") == 0


def test_poll_that_raises_reports_failure_and_the_loop_keeps_running():
    registry = CollectorRegistry()
    calls = []

    def poll():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return PollResult((_family(5),), True)

    loop = _loop(poll, registry, interval=0.01)
    registry.register(PolledMetricsCollector([loop]))
    loop.start()
    deadline = time.monotonic() + 5
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    loop.stop.set()
    loop.join(5)

    assert len(calls) >= 2
    assert _value(registry, "prefect_test_value") == 5
