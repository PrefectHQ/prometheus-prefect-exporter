import asyncio
import os
import threading
from urllib.parse import urlparse

import pytest

from tests.integration.prefect_rest import PrefectRest
from tests.stream_fakes import Relay


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def api_url():
    url = os.environ.get("PREFECT_INTEGRATION_API_URL")
    if not url:
        pytest.fail(
            "Set PREFECT_INTEGRATION_API_URL to a Prefect server started with "
            "tests/integration/compose.override.yml"
        )
    return url.rstrip("/")


@pytest.fixture
def prefect(api_url):
    return PrefectRest(api_url)


class LoopThread:
    """An event loop on a background thread, for asyncio test helpers."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(10)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


class RelayControl:
    """Operates a Relay running on a LoopThread from the test's thread."""

    def __init__(self, relay, loop):
        self._relay = relay
        self._loop = loop

    async def _cut(self):
        self._relay.cut()

    async def _set_refusing(self, refusing):
        self._relay.refusing = refusing

    def cut(self):
        self._loop.call(self._cut())

    def refuse(self, refusing=True):
        self._loop.call(self._set_refusing(refusing))


@pytest.fixture
def relay(api_url):
    """A TCP relay in front of the server; yields (control, relayed API URL)."""
    parsed = urlparse(api_url)
    with LoopThread() as loop:
        relay = Relay(parsed.port or 80, upstream_host=parsed.hostname)
        loop.call(relay.__aenter__())
        try:
            yield (
                RelayControl(relay, loop),
                f"http://127.0.0.1:{relay.port}{parsed.path}",
            )
        finally:
            loop.call(relay.__aexit__())
