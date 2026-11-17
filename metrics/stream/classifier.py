import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Hashable, Optional

TERMINAL_STATE_TYPES = frozenset({"COMPLETED", "FAILED", "CRASHED", "CANCELLED"})

FLOW_RUN_RESOURCE_PREFIX = "prefect.flow-run."


@dataclass(frozen=True)
class TerminalLabels:
    """The label values of `prefect_flow_runs_terminal_total` for one terminal state."""

    deployment_name: str
    flow_name: str
    work_pool_name: str
    work_queue_name: str
    state_type: str
    state_name: str


@dataclass(frozen=True)
class Classification:
    """
    What one flow-run event means for the stream metrics.

    `outcome` is "counted" (the first sighting of an episode's terminal state),
    "duplicate" (a terminal state already counted for that episode) or
    "ignored" (not a terminal state). `missing_run_count` is True for a
    terminal event with no `prefect.run-count`, counted under run count 0.
    """

    outcome: str
    missing_run_count: bool = False
    labels: Optional[TerminalLabels] = None
    duration_seconds: Optional[float] = None


class ExpiringKeys:
    """
    Keys held for a fixed time after they were first added, in insertion
    order so expiry pops from the front.
    """

    def __init__(self, ttl_seconds: float, clock: Callable[[], float]) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._expires_at: OrderedDict[Hashable, float] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._expires_at:
            key, expires_at = next(iter(self._expires_at.items()))
            if expires_at > now:
                return
            self._expires_at.popitem(last=False)

    def add(self, key: Hashable) -> bool:
        """Add `key`. Returns False if it was already held."""
        now = self.clock()
        self._prune(now)
        if key in self._expires_at:
            return False
        self._expires_at[key] = now + self.ttl_seconds
        return True

    def __len__(self) -> int:
        self._prune(self.clock())
        return len(self._expires_at)


class RunningTimes:
    """
    The state timestamp of each run's latest RUNNING-type event, held until
    the run's terminal event or the time limit, whichever comes first.
    """

    def __init__(self, ttl_seconds: float, clock: Callable[[], float]) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._entries: OrderedDict[str, tuple[datetime, float]] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._entries:
            run_id, (_, expires_at) = next(iter(self._entries.items()))
            if expires_at > now:
                return
            self._entries.popitem(last=False)

    def record(self, run_id: str, started: datetime) -> None:
        now = self.clock()
        self._prune(now)
        self._entries[run_id] = (started, now + self.ttl_seconds)
        self._entries.move_to_end(run_id)

    def pop(self, run_id: str) -> Optional[datetime]:
        self._prune(self.clock())
        entry = self._entries.pop(run_id, None)
        return None if entry is None else entry[0]

    def __len__(self) -> int:
        self._prune(self.clock())
        return len(self._entries)


def _parse_timestamp(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


def _related_names(event: dict) -> dict:
    return {
        related.get("prefect.resource.role"): related.get("prefect.resource.name") or ""
        for related in event.get("related") or []
    }


class FlowRunEventClassifier:
    """
    Turns flow-run state events into terminal counts and run durations.

    Each terminal state type an episode (a run id and its run count) enters
    counts once while the episode is in duplicate memory.
    """

    def __init__(
        self,
        duplicate_memory_seconds: float = 24 * 3600,
        running_times_seconds: float = 7 * 24 * 3600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.counted = ExpiringKeys(duplicate_memory_seconds, clock)
        self.running_times = RunningTimes(running_times_seconds, clock)

    def classify(self, event: dict) -> Classification:
        resource = event.get("resource") or {}
        resource_id = resource.get("prefect.resource.id") or ""
        state_type = resource.get("prefect.state-type")
        if not resource_id.startswith(FLOW_RUN_RESOURCE_PREFIX) or not state_type:
            return Classification("ignored")
        run_id = resource_id.removeprefix(FLOW_RUN_RESOURCE_PREFIX)
        state_time = _parse_timestamp(
            resource.get("prefect.state-timestamp")
        ) or _parse_timestamp(event.get("occurred"))

        if state_type == "RUNNING":
            if state_time is not None:
                self.running_times.record(run_id, state_time)
            return Classification("ignored")
        if state_type not in TERMINAL_STATE_TYPES:
            return Classification("ignored")

        raw_run_count = resource.get("prefect.run-count")
        try:
            run_count = int(raw_run_count)
            missing_run_count = False
        except (TypeError, ValueError):
            run_count = 0
            missing_run_count = True

        if not self.counted.add((run_id, run_count, state_type)):
            return Classification("duplicate", missing_run_count)

        related = _related_names(event)
        labels = TerminalLabels(
            deployment_name=related.get("deployment", ""),
            flow_name=related.get("flow", ""),
            work_pool_name=related.get("work-pool", ""),
            work_queue_name=related.get("work-queue", ""),
            state_type=state_type,
            state_name=resource.get("prefect.state-name") or "",
        )
        running_since = self.running_times.pop(run_id)
        return Classification(
            "counted",
            missing_run_count,
            labels,
            self._duration(event, state_time, running_since),
        )

    @staticmethod
    def _duration(
        event: dict, state_time: Optional[datetime], running_since: Optional[datetime]
    ) -> Optional[float]:
        """
        Seconds the run spent in the RUNNING-type state it left, or None when
        it left another state or the start is unknown.

        Prefect Cloud's events carry the prior state's timestamp; open-source
        servers' do not, so the start falls back to the run's last RUNNING-type
        event this process received.
        """
        initial_state = (event.get("payload") or {}).get("initial_state") or {}
        if initial_state.get("type") != "RUNNING" or state_time is None:
            return None
        started = _parse_timestamp(initial_state.get("timestamp")) or running_since
        if started is None:
            return None
        return max(0.0, (state_time - started).total_seconds())
