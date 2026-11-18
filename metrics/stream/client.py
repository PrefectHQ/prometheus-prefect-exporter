import asyncio
import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException
from websockets.typing import Subprotocol

from metrics.health import StreamHealth
from metrics.stream.classifier import FlowRunEventClassifier
from metrics.stream.counters import FlowRunStreamMetrics
from metrics.stream.protocol import (
    auth_message,
    close_kind,
    events_out_url,
    filter_message,
)

# Backfill starts this far before the last received event, as in Prefect's own
# subscriber, to cover events that arrive slightly out of order.
CURSOR_OVERLAP = timedelta(minutes=1)


@dataclass(frozen=True)
class StreamSettings:
    """
    Settings of the event stream subscription. The defaults are the ones the
    exporter runs with; tests shorten them.
    """

    api_url: str
    token: Optional[str]
    # The longest replay the server gives: 2 minutes on Prefect Cloud, 15 on
    # an open-source server.
    backfill_window: float
    ping_interval: float = 20.0
    ping_timeout: float = 20.0
    # Prefect Cloud ends every websocket at 600 seconds, so the socket is
    # replaced before then.
    replace_after: float = 540.0
    # A socket that has delivered no event counts as delivering once it has
    # stayed open this long. Prefect Cloud re-checks for late events shortly
    # after connect, and this waits past that.
    delivering_grace: float = 30.0
    immediate_retries: int = 2
    backoff_initial: float = 1.0
    backoff_max: float = 60.0
    refusal_retry: float = 300.0
    backfill_failures_before_fallback: int = 3
    open_timeout: float = 20.0
    # Added to the refusal log, such as the scope a Prefect Cloud key needs.
    refusal_hint: str = ""


class Refused(Exception):
    """The server refused the subscription."""

    def __init__(self, detail: str, handshake_status: Optional[int] = None) -> None:
        super().__init__(detail)
        self.handshake_status = handshake_status


class SubscribeFailed(Exception):
    """A subscription could not be opened; `kind` is the reconnect reason."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind


class Subscription:
    """One open `/events/out` socket and the tasks that read and ping it."""

    def __init__(self, ws: ClientConnection, backfill: bool, connected_at: float):
        self.ws = ws
        self.backfill = backfill
        self.connected_at = connected_at
        self.last_alive = connected_at
        self.delivering = asyncio.Event()
        self.ended = asyncio.Event()
        self.end_kind: Optional[str] = None
        self.replace_due = 0.0
        self.tasks: list[asyncio.Task] = []

    def end(self, kind: str) -> None:
        """Record how the subscription ended. The first call wins."""
        if self.end_kind is None:
            self.end_kind = kind
            self.ended.set()

    async def close(self, kind: str) -> None:
        self.end(kind)
        for task in self.tasks:
            if task is not asyncio.current_task():
                task.cancel()
        await self.ws.close()


class EventStream:
    """
    Holds the exporter's `/events/out` subscription and feeds each flow-run
    event to the classifier and the stream metrics.
    """

    def __init__(
        self,
        settings: StreamSettings,
        classifier: FlowRunEventClassifier,
        metrics: FlowRunStreamMetrics,
        health: StreamHealth,
        logger: logging.Logger,
        stream_disabled: bool = False,
        wall: Callable[[], float] = time.time,
        rng: Optional[random.Random] = None,
    ) -> None:
        """
        Args:
            settings (StreamSettings): Where and how to subscribe.
            classifier (FlowRunEventClassifier): Classifies each event.
            metrics (FlowRunStreamMetrics): Records counted terminal states.
            health (StreamHealth): The stream's health metrics.
            logger (logging.Logger): The logger.
            stream_disabled (bool): The server's outbound stream is off, so
                the subscription is reported as refused.
            wall (callable): The current time in seconds since the epoch.
            rng (random.Random, optional): The source of backoff jitter.
        """
        self.settings = settings
        self.classifier = classifier
        self.metrics = metrics
        self.health = health
        self.logger = logger
        self.stream_disabled = stream_disabled
        self.wall = wall
        self.rng = rng or random.Random()
        self.url = events_out_url(settings.api_url)

        self.cursor: Optional[datetime] = None
        self.disconnected_since: Optional[float] = None
        self.backfill_failures = 0
        self.failed_attempts = 0
        self.replacement_failures = 0
        self.first_connect = True
        self.open_subscriptions: set[Subscription] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop: Optional[asyncio.Event] = None
        # Set from any thread; `run` checks it once its own stop event exists.
        self._stop_requested = threading.Event()

    # Lifecycle

    def stop_threadsafe(self) -> None:
        """Stop `run` from another thread, whether or not it is running."""
        self._stop_requested.set()
        loop, stop = self._loop, self._stop
        if loop is None or stop is None:
            return
        try:
            loop.call_soon_threadsafe(stop.set)
        except RuntimeError:
            # The loop has closed: `run` already returned.
            pass

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), max(0.0, seconds))
        except TimeoutError:
            pass

    def _backoff(self, failed_attempts: int) -> float:
        if failed_attempts <= self.settings.immediate_retries:
            return 0.0
        exponent = failed_attempts - self.settings.immediate_retries - 1
        delay = min(
            self.settings.backoff_max, self.settings.backoff_initial * 2**exponent
        )
        return self.rng.uniform(delay / 2, delay)

    async def run(self) -> None:
        """Subscribe, and resubscribe after every close, until stopped."""
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        if self._stop_requested.is_set():
            return
        if self.stream_disabled:
            self.health.refused.set(1)
            self.logger.warning(
                "The server's outbound event stream is disabled, so no flow-run "
                "terminal states will be counted"
            )

        current: Optional[Subscription] = None
        try:
            while not self._stop.is_set():
                try:
                    current = await self._step(current)
                except Exception:
                    # A bug or an unexpected reply must not end the stream; drop
                    # the subscription and reconnect with backoff.
                    # Close every open subscription: the failed step may have
                    # opened one besides `current`.
                    await self._close_all("error")
                    current = None
                    self.logger.exception("Event stream failed; reconnecting")
                    self.health.reconnects.labels("error").inc()
                    self.failed_attempts += 1
                    await self._sleep(
                        max(
                            self.settings.backoff_initial,
                            self._backoff(self.failed_attempts),
                        )
                    )
        finally:
            await self._close_all("stopped")

    async def _close_all(self, kind: str) -> None:
        """
        Close every open subscription, and start the disconnected time at the
        last sign of life among them.
        """
        subscriptions = list(self.open_subscriptions)
        if subscriptions:
            self._note_disconnected(max(s.last_alive for s in subscriptions))
        for subscription in subscriptions:
            await subscription.close(kind)
            self.open_subscriptions.discard(subscription)
        self._update_connected()

    def _wants_backfill(self) -> bool:
        return self.backfill_failures < self.settings.backfill_failures_before_fallback

    async def _step(self, current: Optional[Subscription]) -> Optional[Subscription]:
        """
        Advance the subscription by one event: open one, replace it, or handle
        its end. Returns the subscription to hold next, or None.
        """
        if current is None:
            backfill = not self.first_connect and self._wants_backfill()
            current = await self._connect(backfill)
            if current is None:
                return None
            self.first_connect = False
            if not backfill:
                self.backfill_failures = 0

        await self._wait_for_end_or_replacement(current)
        if self._stop.is_set():
            return current
        if current.end_kind is None:
            replacement = await self._replace(current)
            if replacement is not None:
                return replacement
            if current.end_kind is None:
                return current

        await self._after_unplanned_end(current)
        return None

    def _log_refusal(self, detail) -> None:
        if getattr(detail, "handshake_status", None) == 404:
            self.logger.error(
                "The event stream endpoint %s was not found (wrong URL or old "
                "server); retrying in %.0f seconds",
                self.url,
                self.settings.refusal_retry,
            )
            return
        self.logger.error(
            "The server refused the event stream subscription (%s); retrying in "
            "%.0f seconds. %s",
            detail,
            self.settings.refusal_retry,
            self.settings.refusal_hint,
        )

    async def _connect(self, backfill: bool) -> Optional[Subscription]:
        attempt_started = self.wall()
        try:
            return await self._subscribe(backfill)
        except Refused as refusal:
            self._note_disconnected(attempt_started)
            self.health.refused.set(1)
            self.health.reconnects.labels("server_close").inc()
            self._log_refusal(refusal)
            await self._sleep(self.settings.refusal_retry)
        except SubscribeFailed as failure:
            self._note_disconnected(attempt_started)
            self.health.reconnects.labels(failure.kind).inc()
            self.failed_attempts += 1
            delay = self._backoff(self.failed_attempts)
            self.logger.warning(
                "Event stream connect failed (%s); retrying in %.1f seconds",
                failure,
                delay,
            )
            await self._sleep(delay)
        return None

    def _note_disconnected(self, since: float) -> None:
        if self.disconnected_since is None:
            self.disconnected_since = since

    # Opening a subscription

    async def _subscribe(self, backfill: bool) -> Subscription:
        now = datetime.fromtimestamp(self.wall(), timezone.utc)
        if backfill and self.cursor is not None:
            since = self.cursor - CURSOR_OVERLAP
        else:
            # Open-source servers also drop live events older than `since`.
            since = now - timedelta(seconds=self.settings.backfill_window)

        try:
            ws = await connect(
                self.url,
                subprotocols=[Subprotocol("prefect")],
                ping_interval=None,
                open_timeout=self.settings.open_timeout,
            )
        except InvalidStatus as err:
            status = err.response.status_code
            kind = close_kind(
                handshake_status=status,
                auth_failed=False,
                close_code=None,
                delivered=False,
                asked_for_backfill=backfill,
            )
            if kind == "refused":
                raise Refused(f"handshake status {status}", status) from err
            raise SubscribeFailed("error", f"handshake status {status}") from err
        except (OSError, TimeoutError, WebSocketException) as err:
            raise SubscribeFailed("error", repr(err)) from err

        try:
            await ws.send(auth_message(self.settings.token))
            raw_reply = await asyncio.wait_for(ws.recv(), self.settings.open_timeout)
            try:
                reply = json.loads(raw_reply)
            except ValueError:
                reply = None
            if not isinstance(reply, dict):
                await ws.close()
                raise SubscribeFailed(
                    "error", f"unexpected reply to the auth message: {raw_reply!r:.200}"
                )
            if reply.get("type") != "auth_success":
                await ws.close()
                raise Refused(reply.get("reason") or reply.get("type"))
            await ws.send(filter_message(since, now, backfill))
        except ConnectionClosed as err:
            kind = close_kind(
                handshake_status=None,
                auth_failed=False,
                close_code=err.rcvd.code if err.rcvd else None,
                delivered=False,
                asked_for_backfill=False,
            )
            if kind == "refused":
                raise Refused(err.rcvd.reason if err.rcvd else "closed") from err
            raise SubscribeFailed(kind, repr(err)) from err
        except TimeoutError as err:
            await ws.close()
            raise SubscribeFailed("error", "no reply to the auth message") from err

        subscription = Subscription(ws, backfill, self.wall())
        subscription.replace_due = asyncio.get_running_loop().time() + (
            self.settings.replace_after
        )
        subscription.tasks = [
            asyncio.create_task(self._receive(subscription)),
            asyncio.create_task(self._keepalive(subscription)),
            asyncio.create_task(self._grace(subscription)),
        ]
        self.open_subscriptions.add(subscription)
        self._update_connected()
        self.logger.info(
            "Subscribed to the event stream (backfill=%s, since=%s)",
            backfill,
            since.isoformat(),
        )
        return subscription

    # Tasks of one subscription

    async def _receive(self, subscription: Subscription) -> None:
        ws = subscription.ws
        try:
            async for raw in ws:
                try:
                    message = json.loads(raw)
                    if message.get("type") == "event":
                        self._handle_event(subscription, message["event"])
                except Exception:
                    # One bad message must not end the subscription.
                    self.logger.exception(
                        "Skipping an event stream message that could not be "
                        "handled: %.200r",
                        raw,
                    )
                    self.health.events.labels("malformed").inc()
        except ConnectionClosed:
            pass
        finally:
            subscription.end(
                close_kind(
                    handshake_status=None,
                    auth_failed=False,
                    close_code=(
                        ws.protocol.close_rcvd.code if ws.protocol.close_rcvd else None
                    ),
                    delivered=subscription.delivering.is_set(),
                    asked_for_backfill=subscription.backfill,
                )
            )
            self.open_subscriptions.discard(subscription)
            self._update_connected()

    async def _keepalive(self, subscription: Subscription) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.ping_interval)
                pong = await subscription.ws.ping()
                try:
                    await asyncio.wait_for(pong, self.settings.ping_timeout)
                except TimeoutError:
                    subscription.end("ping_timeout")
                    self.logger.warning(
                        "No reply to an event stream ping in %.0f seconds",
                        self.settings.ping_timeout,
                    )
                    subscription.ws.transport.abort()
                    return
                subscription.last_alive = self.wall()
        except ConnectionClosed:
            return
        except Exception:
            self.logger.exception("Event stream keepalive failed")
            subscription.end("error")
            subscription.ws.transport.abort()

    async def _grace(self, subscription: Subscription) -> None:
        await asyncio.sleep(self.settings.delivering_grace)
        self._mark_delivering(subscription)

    def _handle_event(self, subscription: Subscription, event: dict) -> None:
        now = self.wall()
        subscription.last_alive = now
        self._mark_delivering(subscription)
        self.health.last_event_timestamp.set(now)

        classification = self.classifier.classify(event)
        self.metrics.record(classification)
        self.health.events.labels(classification.outcome).inc()
        if classification.missing_run_count:
            self.health.events.labels("missing_run_count").inc()
        self._advance_cursor(event.get("occurred"), now)

    def _advance_cursor(self, occurred, now: float) -> None:
        """Moves the backfill cursor to `occurred`, clamped to now."""
        # Called only after the event was handled, so an event that raised
        # leaves the cursor where the last handled event put it.
        if not occurred:
            return
        try:
            when = datetime.fromisoformat(occurred)
        except (TypeError, ValueError):
            self.logger.warning("Event with unparseable occurred %r", occurred)
            return
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        self.cursor = min(when, datetime.fromtimestamp(now, timezone.utc))

    def _mark_delivering(self, subscription: Subscription) -> None:
        if subscription.delivering.is_set() or subscription.end_kind is not None:
            return
        subscription.delivering.set()
        self.failed_attempts = 0
        self.replacement_failures = 0
        if subscription.backfill:
            self.backfill_failures = 0
        if not self.stream_disabled:
            self.health.refused.set(0)
        self._account_disconnection(subscription)

    def _account_disconnection(self, subscription: Subscription) -> None:
        """
        Add the time from the last sign of the previous subscription to this
        one's connect to the disconnected time, and the part of it that
        backfill did not replay to the gap.
        """
        if self.disconnected_since is None:
            return
        disconnected = max(0.0, subscription.connected_at - self.disconnected_since)
        if subscription.backfill:
            covered_from = subscription.connected_at - self.settings.backfill_window
            gap = max(0.0, covered_from - self.disconnected_since)
        else:
            gap = disconnected
        self.health.disconnected_seconds.inc(disconnected)
        self.health.gap_seconds.inc(gap)
        self.disconnected_since = None

    def _update_connected(self) -> None:
        self.health.connected.set(1 if self.open_subscriptions else 0)

    # Waiting, ending and replacing

    async def _wait_for_end_or_replacement(self, subscription: Subscription) -> None:
        timeout = subscription.replace_due - asyncio.get_running_loop().time()
        waiters = [
            asyncio.create_task(subscription.ended.wait()),
            asyncio.create_task(self._stop.wait()),
        ]
        try:
            await asyncio.wait(
                waiters, timeout=max(0.0, timeout), return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for waiter in waiters:
                waiter.cancel()

    async def _after_unplanned_end(self, subscription: Subscription) -> None:
        kind = subscription.end_kind
        await subscription.close(kind)
        self.open_subscriptions.discard(subscription)
        self._update_connected()

        if kind == "backfill_failure":
            self.backfill_failures += 1
            self.health.backfill_failures.inc()
            self.health.reconnects.labels("server_close").inc()
            self.logger.warning(
                "The server closed the event stream while replaying backfill "
                "(%d in a row)",
                self.backfill_failures,
            )
            self._note_disconnected(subscription.connected_at)
        elif kind == "refused":
            self.health.refused.set(1)
            self.health.reconnects.labels("server_close").inc()
            self._note_disconnected(subscription.connected_at)
            self._log_refusal(subscription.ws.close_reason or "closed")
            await self._sleep(self.settings.refusal_retry)
            return
        else:
            # A subscription that ended before it delivered still held the
            # stream from its connect, so the time before that is accounted.
            self._account_disconnection(subscription)
            self.disconnected_since = subscription.last_alive
            self.health.reconnects.labels(kind).inc()
            self.logger.warning("The event stream closed (%s); reconnecting", kind)

        self.failed_attempts += 1
        await self._sleep(self._backoff(self.failed_attempts))

    async def _replace(self, current: Subscription) -> Optional[Subscription]:
        """
        Open a new subscription beside `current`, with backfill unless the
        fallback threshold was reached, and close `current` once the new one is
        delivering.

        Returns:
            Subscription: The new subscription, or None if it failed; then
            `current` is kept and the replacement is tried again later.
        """
        backfill = self._wants_backfill()
        try:
            replacement = await self._subscribe(backfill=backfill)
        except (Refused, SubscribeFailed) as err:
            self.logger.warning("Event stream replacement failed to connect: %s", err)
            self._retry_replacement_later(current)
            return None

        waiters = [
            asyncio.create_task(replacement.delivering.wait()),
            asyncio.create_task(replacement.ended.wait()),
            asyncio.create_task(self._stop.wait()),
        ]
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()

        if not replacement.delivering.is_set():
            if replacement.end_kind == "backfill_failure":
                self.backfill_failures += 1
                self.health.backfill_failures.inc()
            await replacement.close(replacement.end_kind or "stopped")
            self.open_subscriptions.discard(replacement)
            self._update_connected()
            self._retry_replacement_later(current)
            return None

        if not backfill:
            self.backfill_failures = 0
        await current.close("replaced")
        self.open_subscriptions.discard(current)
        self._update_connected()
        return replacement

    def _retry_replacement_later(self, current: Subscription) -> None:
        self.replacement_failures += 1
        delay = max(
            self.settings.backoff_initial,
            self._backoff(self.settings.immediate_retries + self.replacement_failures),
        )
        current.replace_due = asyncio.get_running_loop().time() + delay
