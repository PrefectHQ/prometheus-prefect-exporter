import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import responses

from metrics.api_metric import PrefectApiMetric
from metrics.csrf import CsrfSession, CsrfToken


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

    token = _api().get_csrf_token("test-client-id")

    assert token == CsrfToken(
        token="server-token",
        expiration=datetime(2026, 11, 17, 12, 30, tzinfo=timezone.utc),
    )
    assert "client=test-client-id" in responses.calls[0].request.url


@responses.activate
def test_csrf_503_with_retry_after_gives_up_without_retrying(monkeypatch):
    sleep_mock = MagicMock()
    monkeypatch.setattr("metrics.api_metric.time.sleep", sleep_mock)
    responses.add(
        responses.GET,
        "http://prefect.test/api/csrf-token",
        status=503,
        headers={"Retry-After": "1200", "Prefect-Maintenance": "true"},
        json={},
    )

    assert _api(max_retries=3).get_csrf_token("c") is None
    assert sleep_mock.call_count == 0
    assert len(responses.calls) == 1


def test_session_fetches_once_and_refetches_after_expiry():
    clock = [datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)]
    issued = []

    def fetch():
        issued.append(clock[0])
        return CsrfToken(f"t{len(issued)}", clock[0] + timedelta(minutes=10))

    session = CsrfSession("client-1", fetch, now=lambda: clock[0])

    assert session.headers() == {
        "Prefect-Csrf-Token": "t1",
        "Prefect-Csrf-Client": "client-1",
    }
    assert session.headers()["Prefect-Csrf-Token"] == "t1"
    clock[0] += timedelta(minutes=10)
    assert session.headers()["Prefect-Csrf-Token"] == "t2"
    assert len(issued) == 2


def test_session_sends_no_headers_when_the_fetch_fails_and_retries_next_time():
    tokens = iter([None, CsrfToken("t", datetime(2999, 1, 1, tzinfo=timezone.utc))])
    session = CsrfSession("client-1", lambda: next(tokens))

    assert session.headers() == {}
    assert session.headers()["Prefect-Csrf-Token"] == "t"


@responses.activate
def test_requests_carry_the_session_csrf_headers():
    responses.add(responses.POST, "http://prefect.test/api/flows/count", json=3)
    token = CsrfToken("t", datetime(2999, 1, 1, tzinfo=timezone.utc))
    api = _api(csrf=CsrfSession("client-1", lambda: token))

    assert api.get_count() == 3
    sent = responses.calls[0].request.headers
    assert sent["Prefect-Csrf-Token"] == "t"
    assert sent["Prefect-Csrf-Client"] == "client-1"
    assert "Prefect-Csrf-Token" not in api.headers


def _api(**overrides):
    kwargs = dict(
        url="http://prefect.test/api",
        headers={"accept": "application/json"},
        max_retries=1,
        timeout=10,
        logger=logging.getLogger("test"),
        enable_pagination=False,
        pagination_limit=200,
        uri="flows",
    )
    kwargs.update(overrides)
    return PrefectApiMetric(**kwargs)
