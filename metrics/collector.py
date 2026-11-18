from typing import Iterable

from metrics.poller import PollLoop


class PolledMetricsCollector:
    """
    Serves the metric families the poll loops last published. A scrape reads
    only stored results and sends no API requests.
    """

    def __init__(self, loops: Iterable[PollLoop]) -> None:
        self.loops = tuple(loops)

    def collect(self):
        for loop in self.loops:
            yield from loop.families()
