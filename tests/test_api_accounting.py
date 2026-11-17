import json
import logging
from unittest.mock import MagicMock

import pytest
import requests
import responses
from prometheus_client import CollectorRegistry

from metrics.deployments import PrefectDeployments
from metrics.flow_runs import PrefectFlowRuns
from metrics.flows import PrefectFlows
from metrics.health import ExporterHealth
from metrics.work_pools import PrefectWorkPools
from metrics.work_queues import PrefectWorkQueues

URL = "http://prefect.test/api"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("metrics.api_metric.time.sleep", MagicMock())


@pytest.fixture
def registry():
    return CollectorRegistry()


def _kwargs(registry, **overrides):
    kwargs = dict(
        url=URL,
        headers={},
        max_retries=3,
        logger=logging.getLogger("test"),
        enable_pagination=True,
        pagination_limit=2,
        timeout=10,
        health=ExporterHealth(registry),
    )
    kwargs.update(overrides)
    return kwargs


def _sample(registry, name, **labels):
    return registry.get_sample_value(name, labels)


@responses.activate
def test_failed_page_marks_the_listing_incomplete_and_counts_it(registry):
    url = f"{URL}/deployments/filter"
    responses.add(responses.POST, url, json=[{"id": "a"}, {"id": "b"}])
    for _ in range(3):
        responses.add(responses.POST, url, status=500)

    listing = PrefectDeployments(**_kwargs(registry)).get_deployments_info()

    assert listing == [{"id": "a"}, {"id": "b"}]
    assert listing.complete is False
    assert (
        _sample(
            registry,
            "prefect_exporter_poll_truncated_total",
            endpoint="/deployments/filter",
        )
        == 1
    )


@responses.activate
def test_listing_read_to_the_empty_page_is_complete(registry):
    url = f"{URL}/deployments/filter"
    responses.add(responses.POST, url, json=[{"id": "a"}, {"id": "b"}])
    responses.add(responses.POST, url, json=[])

    listing = PrefectDeployments(**_kwargs(registry)).get_deployments_info()

    assert listing.complete is True
    assert (
        _sample(
            registry,
            "prefect_exporter_poll_truncated_total",
            endpoint="/deployments/filter",
        )
        is None
    )


@responses.activate
def test_full_page_without_pagination_counts_as_truncated(registry):
    responses.add(
        responses.POST, f"{URL}/flows/filter", json=[{"id": "a"}, {"id": "b"}]
    )

    listing = PrefectFlows(
        **_kwargs(registry, enable_pagination=False)
    ).get_flows_info()

    assert listing.complete is False
    assert len(responses.calls) == 1
    assert (
        _sample(
            registry, "prefect_exporter_poll_truncated_total", endpoint="/flows/filter"
        )
        == 1
    )


@responses.activate
def test_api_errors_are_counted_per_attempt_by_endpoint_and_status(registry):
    for _ in range(3):
        responses.add(responses.POST, f"{URL}/deployments/count", status=502)

    assert PrefectDeployments(**_kwargs(registry)).get_count() is None
    assert (
        _sample(
            registry,
            "prefect_exporter_api_errors_total",
            endpoint="/deployments/count",
            status="502",
        )
        == 3
    )


@responses.activate
def test_timeouts_are_counted_with_status_timeout(registry):
    responses.add(
        responses.POST,
        f"{URL}/flows/count",
        body=requests.exceptions.ReadTimeout("slow"),
    )

    PrefectFlows(**_kwargs(registry, max_retries=1)).get_count()

    assert (
        _sample(
            registry,
            "prefect_exporter_api_errors_total",
            endpoint="/flows/count",
            status="timeout",
        )
        == 1
    )


@responses.activate
def test_work_queue_status_errors_use_the_route_template(registry):
    responses.add(responses.GET, f"{URL}/work_queues/wq-123/status", status=500)

    status = PrefectWorkQueues(
        **_kwargs(registry, max_retries=1)
    ).get_work_queue_status_info("wq-123")

    assert status == {}
    assert (
        _sample(
            registry,
            "prefect_exporter_api_errors_total",
            endpoint="/work_queues/{id}/status",
            status="500",
        )
        == 1
    )


@responses.activate
def test_flow_runs_fall_back_to_filter_when_filter_minimal_is_missing(registry):
    responses.add(responses.POST, f"{URL}/flow_runs/filter-minimal", status=404)
    responses.add(responses.POST, f"{URL}/flow_runs/filter", json=[])

    flow_runs = PrefectFlowRuns(**_kwargs(registry), offset_minutes=3)
    flow_runs.get_all_flow_runs_info()
    flow_runs.get_ongoing_flow_runs_info()

    urls = [call.request.url for call in responses.calls]
    assert urls.count(f"{URL}/flow_runs/filter-minimal") == 1
    assert urls.count(f"{URL}/flow_runs/filter") == 2
    assert (
        _sample(
            registry,
            "prefect_exporter_api_errors_total",
            endpoint="/flow_runs/filter-minimal",
            status="404",
        )
        is None
    )


@responses.activate
def test_flow_runs_list_through_filter_minimal_when_the_server_has_it(registry):
    responses.add(responses.POST, f"{URL}/flow_runs/filter-minimal", json=[])

    PrefectFlowRuns(**_kwargs(registry), offset_minutes=3).get_all_flow_runs_info()

    urls = {call.request.url for call in responses.calls}
    assert urls == {f"{URL}/flow_runs/filter-minimal"}


@responses.activate
@pytest.mark.parametrize(
    "make, path, sort",
    [
        (
            lambda kw: PrefectDeployments(**kw).get_deployments_info(),
            "deployments",
            "NAME_ASC",
        ),
        (lambda kw: PrefectFlows(**kw).get_flows_info(), "flows", "NAME_ASC"),
        (
            lambda kw: PrefectFlowRuns(
                **kw, offset_minutes=3
            ).get_ongoing_flow_runs_info(),
            "flow_runs",
            "ID_DESC",
        ),
        (lambda kw: PrefectWorkPools(**kw).get_work_pools_info(), "work_pools", None),
    ],
)
def test_every_listing_sends_its_explicit_sort(registry, make, path, sort):
    responses.add(responses.POST, f"{URL}/{path}/filter-minimal", status=404)
    responses.add(responses.POST, f"{URL}/{path}/filter", json=[])

    make(_kwargs(registry))

    bodies = [
        json.loads(call.request.body)
        for call in responses.calls
        if call.request.url == f"{URL}/{path}/filter"
    ]
    assert bodies
    assert all(body.get("sort") == sort for body in bodies)
