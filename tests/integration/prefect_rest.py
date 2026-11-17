"""Drives flow runs on a Prefect server through its REST API, without the prefect package."""

import time
import uuid

import requests


class PrefectRest:
    def __init__(self, api_url):
        self.api_url = api_url.rstrip("/")

    def post(self, path, body):
        # A SQLite-backed server answers 503 while its database is locked.
        for attempt in range(5):
            resp = requests.post(f"{self.api_url}{path}", json=body, timeout=30)
            if resp.status_code != 503:
                break
            time.sleep(0.5 * (attempt + 1))
        resp.raise_for_status()
        return resp.json()

    def deployment(self, label):
        """Create a work pool, a flow and a deployment, all named after `label`."""
        suffix = uuid.uuid4().hex[:8]
        pool = f"pool-{label}-{suffix}"
        self.post("/work_pools/", {"name": pool, "type": "process"})
        flow = self.post("/flows/", {"name": f"flow-{label}-{suffix}"})
        deployment = self.post(
            "/deployments/",
            {
                "name": f"deployment-{label}-{suffix}",
                "flow_id": flow["id"],
                "work_pool_name": pool,
            },
        )
        return {
            "id": deployment["id"],
            "deployment_name": deployment["name"],
            "flow_name": flow["name"],
            "work_pool_name": pool,
            "work_queue_name": deployment["work_queue_name"],
        }

    def run(self, deployment, name="run"):
        return self.post(
            f"/deployments/{deployment['id']}/create_flow_run", {"name": name}
        )["id"]

    def set_state(self, run_id, state_type, name=None):
        state = {"type": state_type}
        if name:
            state["name"] = name
        # A server may answer REJECT and set another state instead, such as
        # Cancelled for a scheduled run asked to cancel.
        return self.post(
            f"/flow_runs/{run_id}/set_state", {"state": state, "force": True}
        )

    def walk(self, run_id, *states):
        """Set each (state type, state name) in order, a moment apart."""
        for state_type, name in states:
            time.sleep(0.05)
            self.set_state(run_id, state_type, name)
