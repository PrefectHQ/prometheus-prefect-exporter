import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from metrics.health import ExporterHealth


@dataclass(frozen=True)
class PollResult:
    """The metric families one poll built, and whether every request succeeded."""

    families: tuple
    complete: bool


@dataclass(frozen=True)
class Snapshot:
    """The metric families served on each scrape until the next poll replaces them."""

    families: tuple
    taken_at: float


class PollLoop(threading.Thread):
    """
    Runs one poll function on a fixed start-to-start interval and publishes
    what it builds for `/metrics` to read.

    A poll that loses data (a failed request or a truncated listing) sets
    `prefect_exporter_poll_success` to 0 and keeps the previous snapshot,
    unless that snapshot is older than `max_stale_intervals` intervals or
    there is none; then the partial result is published.
    """

    def __init__(
        self,
        name: str,
        poll: Callable[[], PollResult],
        interval: float,
        health: ExporterHealth,
        stop: threading.Event,
        logger: logging.Logger,
        clock: Callable[[], float] = time.monotonic,
        max_stale_intervals: int = 3,
    ) -> None:
        super().__init__(name=f"poller-{name}", daemon=True)
        self.poller = name
        self._poll = poll
        self.interval = interval
        self.health = health
        self.stop = stop
        self.logger = logger
        self.clock = clock
        self.max_stale_intervals = max_stale_intervals
        self.snapshot: Optional[Snapshot] = None

    def run(self) -> None:
        while not self.stop.is_set():
            started = self.clock()
            self.poll_once()
            self.stop.wait(max(0.0, self.interval - (self.clock() - started)))

    def poll_once(self) -> None:
        started = self.clock()
        try:
            result = self._poll()
        except Exception:
            # The loop must outlive a bug in one poll; the next poll retries.
            self.logger.exception("Poll %s failed", self.poller)
            result = None
        finished = self.clock()
        self.health.poll_duration.labels(self.poller).observe(finished - started)
        complete = result is not None and result.complete
        success = self.health.poll_success.labels(self.poller)
        if not complete:
            success.set(0)

        if result is None:
            return
        if complete or self._snapshot_is_stale(finished):
            self.snapshot = Snapshot(families=result.families, taken_at=finished)
        else:
            self.logger.warning(
                "Poll %s lost data; serving the previous result", self.poller
            )
        if complete:
            # Set after the snapshot, so a reader of 1 finds the results.
            success.set(1)

    def _snapshot_is_stale(self, now: float) -> bool:
        if self.snapshot is None:
            return True
        return now - self.snapshot.taken_at > self.max_stale_intervals * self.interval

    def families(self) -> tuple:
        snapshot = self.snapshot
        return () if snapshot is None else snapshot.families
