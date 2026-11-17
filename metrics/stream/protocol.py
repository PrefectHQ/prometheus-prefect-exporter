import json
from datetime import datetime, timedelta, timezone
from typing import Optional

# Live events newer than `until` are dropped by open-source servers, so the
# window ends far ahead, as in Prefect's own subscriber.
FILTER_UNTIL_AHEAD = timedelta(days=365)

EVENT_FILTER = {
    "prefix": ["prefect.flow-run."],
    # Pull-step events are named prefect.flow-run.pull-step.executed and
    # .failed, so they are excluded by prefix.
    "exclude_prefix": ["prefect.flow-run.heartbeat", "prefect.flow-run.pull-step."],
}

POLICY_VIOLATION = 1008
INTERNAL_ERROR = 1011


def events_out_url(api_url: str) -> str:
    """The `/events/out` websocket URL of a Prefect API URL."""
    if api_url.startswith("https://"):
        base = "wss://" + api_url.removeprefix("https://")
    elif api_url.startswith("http://"):
        base = "ws://" + api_url.removeprefix("http://")
    else:
        base = api_url
    return base.rstrip("/") + "/events/out"


def auth_message(token: Optional[str]) -> str:
    return json.dumps({"type": "auth", "token": token or None})


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def filter_message(since: datetime, now: datetime, backfill: bool) -> str:
    """
    The subscription's filter message.

    Args:
        since (datetime): The start of the `occurred` window, which is also
            where backfill starts. The server clamps it to its maximum.
        now (datetime): The current time; the window ends a year after it.
        backfill (bool): Whether the server replays events since `since`.
    """
    return json.dumps(
        {
            "type": "filter",
            "backfill": backfill,
            "filter": {
                "event": EVENT_FILTER,
                "occurred": {
                    "since": _iso(since),
                    "until": _iso(now + FILTER_UNTIL_AHEAD),
                },
            },
        }
    )


def close_kind(
    *,
    handshake_status: Optional[int],
    auth_failed: bool,
    close_code: Optional[int],
    saw_event: bool,
    asked_for_backfill: bool,
) -> str:
    """
    Classify how a subscription ended.

    This reads close codes, on the assumption that Prefect Cloud's and
    open-source servers keep these behaviours: a refused subscription is
    rejected at the handshake with a 4xx, or answered with an `auth_failure`
    message, or closed with 1008; and an error while replaying backfill, which
    happens before any live event, escapes the server's handler, so the
    server closes with 1011.

    Returns:
        str: "refused", "backfill_failure", "server_close" (any other close
        frame from the server) or "error" (no close frame: a dropped
        connection, a failed handshake, a protocol error).
    """
    if handshake_status is not None and 400 <= handshake_status < 500:
        return "refused"
    if auth_failed:
        return "refused"
    if close_code == POLICY_VIOLATION and not saw_event:
        return "refused"
    if close_code == INTERNAL_ERROR and not saw_event and asked_for_backfill:
        return "backfill_failure"
    if close_code is not None and close_code != 1006:
        return "server_close"
    return "error"
