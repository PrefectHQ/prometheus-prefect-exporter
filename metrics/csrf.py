from dataclasses import dataclass
from datetime import datetime, timezone


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
