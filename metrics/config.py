import base64
import os
import re
from dataclasses import dataclass
from typing import Mapping

# Prefect Cloud workspace API URLs end in /accounts/<id>/workspaces/<id>.
_CLOUD_WORKSPACE_PATH = re.compile(r"/accounts/[^/]+/workspaces/[^/]+/?$")


def _flag(env: Mapping[str, str], name: str, default: str) -> bool:
    return str(env.get(name, default)) == "True"


@dataclass(frozen=True)
class Config:
    """The exporter's settings, read from environment variables."""

    log_level: str
    max_retries: int
    metrics_addr: str
    metrics_port: int
    failed_runs_offset_minutes: int
    failed_runs_limit: int
    url: str
    api_key: str
    api_auth_string: str
    request_timeout: float
    csrf_enabled: bool
    enable_pagination: bool
    pagination_limit: int
    enable_flow_run_name_label: bool
    inventory_poll_interval: float
    run_poll_interval: float

    @property
    def is_cloud(self) -> bool:
        return bool(_CLOUD_WORKSPACE_PATH.search(self.url))

    def headers(self) -> dict:
        """The headers sent with every API request."""
        headers = {"accept": "application/json", "Content-Type": "application/json"}
        if self.api_auth_string:
            encoded = base64.b64encode(self.api_auth_string.encode("utf-8")).decode(
                "utf-8"
            )
            headers["Authorization"] = f"Basic {encoded}"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        return cls(
            log_level=str(env.get("LOG_LEVEL", "INFO")),
            max_retries=int(env.get("MAX_RETRIES", "3")),
            metrics_addr=env.get("METRICS_ADDR", "0.0.0.0"),
            metrics_port=int(env.get("METRICS_PORT", "8000")),
            failed_runs_offset_minutes=int(
                env.get("FAILED_RUNS_OFFSET_MINUTES", "10080")
            ),
            failed_runs_limit=int(env.get("FAILED_RUNS_LIMIT", "10")),
            url=str(env.get("PREFECT_API_URL", "http://localhost:4200/api")).rstrip(
                "/"
            ),
            api_key=str(env.get("PREFECT_API_KEY", "")),
            api_auth_string=str(env.get("PREFECT_API_AUTH_STRING", "")),
            request_timeout=float(env.get("REQUEST_TIMEOUT_SECONDS", "60")),
            csrf_enabled=_flag(env, "PREFECT_CSRF_ENABLED", "False"),
            enable_pagination=_flag(env, "PAGINATION_ENABLED", "True"),
            pagination_limit=int(env.get("PAGINATION_LIMIT", "200")),
            enable_flow_run_name_label=_flag(
                env, "ENABLE_FLOW_RUN_NAME_LABEL", "False"
            ),
            inventory_poll_interval=float(
                env.get("INVENTORY_POLL_INTERVAL_SECONDS", "300")
            ),
            run_poll_interval=float(env.get("RUN_POLL_INTERVAL_SECONDS", "60")),
        )
