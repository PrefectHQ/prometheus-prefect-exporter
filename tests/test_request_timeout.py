import logging

import responses

from metrics.healthz import PrefectHealthz
from metrics.metrics import PrefectMetrics

URL = "http://prefect.test/api"


@responses.activate(assert_all_requests_are_fired=True)
def test_timeout_is_passed_to_every_request():
    responses.add(responses.GET, f"{URL}/health", json={})
    responses.add(
        responses.GET,
        f"{URL}/csrf-token",
        json={
            "token": "t",
            "client": "test-client-id",
            "expiration": "2999-01-01T00:00:00Z",
        },
    )
    responses.add(responses.POST, f"{URL}/deployments/filter", json=[])
    responses.add(responses.POST, f"{URL}/flows/filter", json=[])
    responses.add(responses.POST, f"{URL}/flow_runs/filter", json=[])
    responses.add(responses.POST, f"{URL}/work_pools/filter", json=[])
    responses.add(
        responses.POST,
        f"{URL}/work_queues/filter",
        json=[{"id": "wq-1", "name": "default"}],
    )
    responses.add(responses.GET, f"{URL}/work_queues/wq-1/status", json={})

    PrefectHealthz(
        url=URL,
        headers={},
        max_retries=1,
        logger=logging.getLogger("test"),
        timeout=7,
    ).get_health_check()
    collector = PrefectMetrics(
        url=URL,
        headers={"accept": "application/json"},
        offset_minutes=3,
        failed_runs_offset_minutes=10080,
        failed_runs_limit=10,
        max_retries=1,
        client_id="test-client-id",
        csrf_enabled=True,
        logger=logging.getLogger("test"),
        enable_pagination=False,
        pagination_limit=200,
        timeout=7,
    )
    list(collector.collect())

    assert {call.request.req_kwargs["timeout"] for call in responses.calls} == {7}
