"""A scripted `/events/out` server and a TCP relay for event stream tests."""

import asyncio
import json
import time
from http import HTTPStatus

from websockets.asyncio.server import serve


class FakeEventsServer:
    """
    A websocket server that answers each connection with the next script in
    `scripts`, or with `default_script` once they run out. A script is an
    async function `(connection, filter_message)` called after a successful
    auth; it returns when the server should close the socket.
    """

    def __init__(self):
        self.scripts = []
        self.filters = []
        self.auths = []
        self.subprotocols = []
        self.connections = 0
        self.refuse_handshake_with = None
        self.auth_reply = {"type": "auth_success"}
        self.open_sockets = set()
        self._server = None

    async def default_script(self, ws, filter_message):
        await ws.wait_closed()

    def _process_request(self, connection, request):
        if self.refuse_handshake_with is not None:
            return connection.respond(
                HTTPStatus(self.refuse_handshake_with), "refused\n"
            )
        return None

    async def _handler(self, ws):
        self.connections += 1
        self.open_sockets.add(ws)
        try:
            self.subprotocols.append(ws.subprotocol)
            auth = json.loads(await ws.recv())
            self.auths.append(auth)
            await ws.send(json.dumps(self.auth_reply))
            if self.auth_reply["type"] != "auth_success":
                await ws.close(1008, self.auth_reply.get("reason", "refused"))
                return
            filter_message = json.loads(await ws.recv())
            self.filters.append(filter_message)
            script = self.scripts.pop(0) if self.scripts else self.default_script
            await script(ws, filter_message)
        finally:
            self.open_sockets.discard(ws)

    async def __aenter__(self):
        self._server = await serve(
            self._handler,
            "127.0.0.1",
            0,
            subprotocols=["prefect"],
            process_request=self._process_request,
            ping_interval=None,
        )
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()

    @property
    def port(self):
        return self._server.sockets[0].getsockname()[1]


class Relay:
    """
    A TCP relay in front of the fake server. `freeze()` stops forwarding on
    the connections open at that moment, so those sockets stay open but pings
    get no reply; later connections pass. `cut()` drops the open connections
    without a close frame.
    """

    def __init__(self, upstream_port):
        self.upstream_port = upstream_port
        self.connections = []
        self._server = None

    async def _pump(self, reader, writer, state):
        try:
            while data := await reader.read(65536):
                if state["frozen"]:
                    continue
                writer.write(data)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    async def _handle(self, client_reader, client_writer):
        upstream_reader, upstream_writer = await asyncio.open_connection(
            "127.0.0.1", self.upstream_port
        )
        state = {"frozen": False, "writers": (client_writer, upstream_writer)}
        self.connections.append(state)
        await asyncio.gather(
            self._pump(client_reader, upstream_writer, state),
            self._pump(upstream_reader, client_writer, state),
        )

    def freeze(self):
        for state in self.connections:
            state["frozen"] = True

    def cut(self):
        for state in self.connections:
            for writer in state["writers"]:
                writer.transport.abort()
        self.connections.clear()

    async def __aenter__(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc):
        self.cut()
        self._server.close()

    @property
    def port(self):
        return self._server.sockets[0].getsockname()[1]


def event_message(event):
    return json.dumps({"type": "event", "event": event})


async def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)
