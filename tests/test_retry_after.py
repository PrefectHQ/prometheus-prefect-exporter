from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock

from metrics.retry_after import (
    detect_retry_after,
    log_retry_after,
    parse_retry_after,
)


class TestParseRetryAfter:
    def test_delta_seconds(self):
        assert parse_retry_after("1200") == 1200.0

    def test_delta_seconds_with_whitespace(self):
        assert parse_retry_after("  30  ") == 30.0

    def test_negative_clamps_to_zero(self):
        assert parse_retry_after("-5") == 0.0

    def test_none(self):
        assert parse_retry_after(None) is None

    def test_empty(self):
        assert parse_retry_after("") is None
        assert parse_retry_after("   ") is None

    def test_garbage(self):
        assert parse_retry_after("soon") is None

    def test_http_date_future(self):
        future = datetime.now(timezone.utc) + timedelta(seconds=60)
        result = parse_retry_after(format_datetime(future, usegmt=True))
        assert result is not None
        assert 50 <= result <= 70

    def test_http_date_past_clamps_to_zero(self):
        past = datetime.now(timezone.utc) - timedelta(seconds=60)
        result = parse_retry_after(format_datetime(past, usegmt=True))
        assert result == 0.0


def _resp(status: int, headers: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.headers = headers or {}
    return m


class TestDetectRetryAfter:
    def test_none_response(self):
        assert detect_retry_after(None) is None

    def test_503_with_retry_after(self):
        signal = detect_retry_after(_resp(503, {"Retry-After": "1200"}))
        assert signal is not None
        assert signal.seconds == 1200.0
        assert signal.status_code == 503
        assert signal.maintenance is False

    def test_503_with_maintenance_header(self):
        signal = detect_retry_after(
            _resp(
                503,
                {"Retry-After": "1200", "Prefect-Maintenance": "true"},
            )
        )
        assert signal is not None
        assert signal.maintenance is True

    def test_maintenance_header_case_insensitive(self):
        signal = detect_retry_after(
            _resp(503, {"Retry-After": "1", "Prefect-Maintenance": "TRUE"})
        )
        assert signal is not None
        assert signal.maintenance is True

    def test_429_with_retry_after(self):
        signal = detect_retry_after(_resp(429, {"Retry-After": "10"}))
        assert signal is not None
        assert signal.status_code == 429

    def test_500_not_triggered(self):
        assert detect_retry_after(_resp(500, {"Retry-After": "10"})) is None

    def test_503_without_header_not_triggered(self):
        assert detect_retry_after(_resp(503, {})) is None

    def test_503_with_unparseable_header_not_triggered(self):
        assert detect_retry_after(_resp(503, {"Retry-After": "soon"})) is None


def test_log_retry_after_maintenance():
    logger = MagicMock()
    signal = detect_retry_after(
        _resp(503, {"Retry-After": "1200", "Prefect-Maintenance": "true"})
    )
    assert signal is not None
    log_retry_after(logger, "https://api/foo", signal)
    args, _ = logger.warning.call_args
    assert "maintenance mode" in args[0] % args[1:]
    assert "https://api/foo" in args[0] % args[1:]


def test_log_retry_after_generic():
    logger = MagicMock()
    signal = detect_retry_after(_resp(429, {"Retry-After": "10"}))
    assert signal is not None
    log_retry_after(logger, "https://api/foo", signal)
    args, _ = logger.warning.call_args
    rendered = args[0] % args[1:]
    assert "server-requested backoff" in rendered
