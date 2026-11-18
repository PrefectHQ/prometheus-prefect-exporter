import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional


@dataclass(frozen=True)
class CsrfToken:
    """A CSRF token issued by a Prefect server's `/csrf-token` endpoint."""

    token: str
    expiration: datetime

    @classmethod
    def from_response(cls, body: dict) -> "CsrfToken":
        """
        Build a token from the JSON body of `GET /csrf-token`.

        Args:
            body (dict): The decoded response, with `token` and `expiration` keys.

        Returns:
            CsrfToken: The token, with a timezone-aware expiration.
        """
        expiration = datetime.fromisoformat(body["expiration"])
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=timezone.utc)
        return cls(token=body["token"], expiration=expiration)

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expiration


class CsrfSession:
    """
    The CSRF headers for one exporter process, shared by every thread that
    calls the API.
    """

    def __init__(
        self,
        client_id: str,
        fetch_token: Callable[[], Optional[CsrfToken]],
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """
        Args:
            client_id (str): The client id the token is issued for.
            fetch_token (callable): Requests a new token, returning None when
                the request failed.
            now (callable): The current time, for tests.
        """
        self.client_id = client_id
        self._fetch_token = fetch_token
        self._now = now
        self._token: Optional[CsrfToken] = None
        self._lock = threading.Lock()

    def headers(self) -> dict:
        """
        Return the CSRF headers, fetching a new token when there is none or
        it has expired. Returns no headers when the fetch fails, so the
        request goes out and the server's refusal is counted as an API error.
        """
        with self._lock:
            if self._token is None or self._token.is_expired(self._now()):
                self._token = self._fetch_token()
            if self._token is None:
                return {}
            return {
                "Prefect-Csrf-Token": self._token.token,
                "Prefect-Csrf-Client": self.client_id,
            }
