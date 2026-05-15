"""Helpers for honoring the HTTP Retry-After header on 429/503 responses."""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Optional

import requests


RETRY_AFTER_HEADER = "Retry-After"
PREFECT_MAINTENANCE_HEADER = "Prefect-Maintenance"
RETRY_AFTER_STATUSES = frozenset({429, 503})


@dataclass(frozen=True)
class RetryAfterSignal:
    seconds: float
    status_code: int
    maintenance: bool


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a Retry-After header value into seconds-from-now.

    Accepts either delta-seconds or an HTTP-date per RFC 7231 section 7.1.3.
    Returns ``None`` if the value is missing or unparseable. Negative
    values clamp to 0.
    """
    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        return max(0.0, float(raw))
    except ValueError:
        pass

    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = (when - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delta)


def detect_retry_after(
    resp: Optional[requests.Response],
) -> Optional[RetryAfterSignal]:
    """Return a RetryAfterSignal if ``resp`` is a 429/503 with Retry-After.

    Returns ``None`` for any other response (including missing response,
    unrelated status codes, or 429/503 without a usable Retry-After).
    """
    if resp is None:
        return None
    if resp.status_code not in RETRY_AFTER_STATUSES:
        return None

    seconds = parse_retry_after(resp.headers.get(RETRY_AFTER_HEADER))
    if seconds is None:
        return None

    maintenance = resp.headers.get(PREFECT_MAINTENANCE_HEADER, "").lower() == "true"
    return RetryAfterSignal(
        seconds=seconds,
        status_code=resp.status_code,
        maintenance=maintenance,
    )


def log_retry_after(logger, endpoint: str, signal: RetryAfterSignal) -> None:
    kind = "maintenance mode" if signal.maintenance else "server-requested backoff"
    logger.warning(
        "Aborting scrape of %s: %s (status=%s, Retry-After=%.0fs)",
        endpoint,
        kind,
        signal.status_code,
        signal.seconds,
    )
