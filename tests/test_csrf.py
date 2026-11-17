import logging
from datetime import datetime, timezone

import pytest
import responses

from metrics.csrf import CsrfToken
from metrics.metrics import PrefectMetrics


@pytest.mark.parametrize(
    "raw",
    [
        "2026-11-17T12:30:00Z",
        "2026-11-17T12:30:00+00:00",
        "2026-11-17T12:30:00",
        "2026-11-17T07:30:00-05:00",
    ],
)
def test_expiration_parses_to_the_same_utc_instant(raw):
    token = CsrfToken.from_response({"token": "abc", "client": "c", "expiration": raw})

    assert token.token == "abc"
    assert token.expiration == datetime(2026, 11, 17, 12, 30, tzinfo=timezone.utc)
    assert token.expiration.tzinfo is not None


def test_is_expired_compares_against_the_expiration():
    token = CsrfToken.from_response(
        {"token": "abc", "expiration": "2026-11-17T12:30:00Z"}
    )

    assert not token.is_expired(datetime(2026, 11, 17, 12, 29, tzinfo=timezone.utc))
    assert token.is_expired(datetime(2026, 11, 17, 12, 30, tzinfo=timezone.utc))


@responses.activate
def test_get_csrf_token_returns_the_parsed_server_token():
    responses.add(
        responses.GET,
        "http://prefect.test/api/csrf-token",
        json={
            "token": "server-token",
            "client": "test-client-id",
            "expiration": "2026-11-17T12:30:00Z",
        },
    )
    metrics = PrefectMetrics(
        url="http://prefect.test/api",
        headers={},
        offset_minutes=3,
        failed_runs_offset_minutes=10080,
        failed_runs_limit=10,
        max_retries=1,
        timeout=10,
        client_id="test-client-id",
        csrf_enabled=True,
        logger=logging.getLogger("test"),
        enable_pagination=False,
        pagination_limit=200,
    )

    token = metrics.get_csrf_token()

    assert token == CsrfToken(
        token="server-token",
        expiration=datetime(2026, 11, 17, 12, 30, tzinfo=timezone.utc),
    )
    assert "client=test-client-id" in responses.calls[0].request.url
