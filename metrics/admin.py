from typing import Optional

from metrics.api_metric import PrefectApiMetric


class PrefectAdmin(PrefectApiMetric):
    """
    Reads an open-source Prefect server's settings. Prefect Cloud has no
    such endpoint.
    """

    uri = "admin"

    def stream_out_enabled(self) -> Optional[bool]:
        """
        Whether the server streams events out on `/events/out`.

        Returns:
            bool: The server's `server.events.stream_out_enabled` setting, or
            None if the settings could not be read.
        """
        resp = self._get(f"{self.uri}/settings", f"/{self.uri}/settings")
        if resp is None:
            return None
        events = (resp.json().get("server") or {}).get("events") or {}
        enabled = events.get("stream_out_enabled")
        return None if enabled is None else bool(enabled)
