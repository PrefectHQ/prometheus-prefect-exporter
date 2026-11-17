import threading
import time
from typing import Optional

import requests
from prometheus_client import CollectorRegistry

from metrics.csrf import CsrfSession, CsrfToken
from metrics.health import ExporterHealth
from metrics.retry_after import detect_retry_after, log_retry_after

_thread_sessions = threading.local()


def _session() -> requests.Session:
    # requests.Session is not safe to share across threads, so each thread
    # keeps its own and still reuses connections.
    session = getattr(_thread_sessions, "session", None)
    if session is None:
        session = requests.Session()
        _thread_sessions.session = session
    return session


class Listing(list):
    """
    The items of a paginated listing. `complete` is False when a page failed
    before the last page was read, so the items are only the first part of the
    listing.
    """

    def __init__(self, items=(), complete: bool = True) -> None:
        super().__init__(items)
        self.complete = complete


class PrefectApiMetric:
    """
    Base class for reading one kind of Prefect resource through the REST API.
    """

    # The sort sent with every listing, or None for endpoints that take no
    # sort. A fixed order keeps offset pagination from skipping or repeating
    # items between pages.
    default_sort: Optional[str] = None

    # The resource's path below the API URL, set by each subclass.
    uri: str = ""

    def __init__(
        self,
        url,
        headers,
        max_retries,
        logger,
        enable_pagination,
        pagination_limit,
        timeout,
        uri: Optional[str] = None,
        health: Optional[ExporterHealth] = None,
        csrf: Optional[CsrfSession] = None,
    ) -> None:
        """
        Initialize the PrefectApiMetric instance.

        Args:
            url (str): The URL of the Prefect instance.
            headers (dict): Headers to be included in HTTP requests.
            max_retries (int): The maximum number of retries for HTTP requests.
            logger (obj): The logger object.
            enable_pagination (bool): Whether to use pagination or not.
            pagination_limit (int): The limit for pagination.
            timeout (float): Timeout in seconds for each HTTP request.
            uri (str, optional): The resource's path below the API URL.
                Defaults to the subclass's `uri`.
            health (ExporterHealth, optional): Where API errors and truncated
                listings are counted. Defaults to a private registry.
            csrf (CsrfSession, optional): Adds CSRF headers to each request.
        """
        self.headers = headers
        if uri is not None:
            self.uri = uri
        self.csrf = csrf
        # Requests that returned None, for pollers to tell a clean poll from
        # one that lost data.
        self.failed_requests = 0
        self.url = url
        self.max_retries = max_retries
        self.logger = logger
        self.enable_pagination = enable_pagination
        self.pagination_limit = pagination_limit
        self.timeout = timeout
        self.health = health or ExporterHealth(CollectorRegistry())

    def _request(
        self,
        method: str,
        path: str,
        endpoint: str,
        data: Optional[dict] = None,
        passthrough_statuses: frozenset = frozenset(),
        attempts: Optional[int] = None,
    ) -> Optional[requests.Response]:
        """
        Send a request, retrying with exponential backoff.

        Args:
            method (str): "GET" or "POST".
            path (str): The path below the API URL, without a leading slash.
            endpoint (str): The route used as the `endpoint` label, with ids
                replaced, such as "/work_queues/{id}/status".
            data (dict, optional): The JSON body of a POST.
            passthrough_statuses (frozenset): Statuses returned to the caller
                at once, without a retry or an error count.
            attempts (int, optional): Overrides `max_retries` for this request.

        Returns:
            requests.Response: The response, or None if all retries failed or
            the server sent Retry-After.
        """
        url = f"{self.url}/{path}"
        headers = self.headers
        if self.csrf is not None:
            headers = {**headers, **self.csrf.headers()}
        attempts = attempts or self.max_retries
        for retry in range(attempts):
            try:
                resp = _session().request(
                    method,
                    url,
                    headers=headers,
                    json=data,
                    timeout=self.timeout,
                )
                if resp.status_code in passthrough_statuses:
                    return resp
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as err:
                self.health.api_errors.labels(endpoint, _error_status(err)).inc()
                signal = detect_retry_after(err.response)
                if signal is not None:
                    log_retry_after(self.logger, url, signal)
                    self.failed_requests += 1
                    return None
                self.logger.error(err)
                if retry < attempts - 1:
                    time.sleep(2**retry)

        self.logger.error("Max retries reached for %s", url)
        self.failed_requests += 1
        return None

    def _post(self, path: str, data: dict, **kwargs) -> Optional[requests.Response]:
        return self._request("POST", path, f"/{path}", data, **kwargs)

    def _get(self, path: str, endpoint: str) -> Optional[requests.Response]:
        return self._request("GET", path, endpoint)

    def get_csrf_token(self, client_id: str) -> Optional[CsrfToken]:
        """
        Request a CSRF token for `client_id`.

        Returns:
            CsrfToken: The token, or None if the request failed.
        """
        resp = self._get(f"csrf-token?client={client_id}", "/csrf-token")
        return None if resp is None else CsrfToken.from_response(resp.json())

    def _get_with_pagination(
        self, base_data: Optional[dict] = None, path: Optional[str] = None
    ) -> Listing:
        """
        Fetch all items from a filter endpoint, page by page, until a page
        comes back empty.

        Args:
            base_data (dict, optional): Filter body sent with every page.
            path (str, optional): The filter path. Defaults to "<uri>/filter".

        Returns:
            Listing: The items read. When a page fails, the items before it,
            with `complete` set to False and the truncation counted.
        """
        path = path or f"{self.uri}/filter"
        limit = self.pagination_limit
        offset = 0
        items = Listing()

        while True:
            data = {**(base_data or {}), "limit": limit, "offset": offset}
            if self.default_sort and "sort" not in data:
                data["sort"] = self.default_sort
            resp = self._post(path, data)
            if resp is None:
                items.complete = False
                self.health.poll_truncated.labels(f"/{path}").inc()
                return items

            page = resp.json()
            if not page:
                break
            items.extend(page)

            if not self.enable_pagination:
                # Without pagination only one page is read, so a full page
                # may leave items unread.
                if len(page) >= limit:
                    items.complete = False
                    self.health.poll_truncated.labels(f"/{path}").inc()
                break

            offset += limit

        return items

    def get_by_ids(self, ids) -> list:
        """
        Fetch the items with the given IDs.

        Returns:
            list: The items found, stopping at the first request that fails.
        """
        ids = sorted({i for i in ids if i is not None})
        items = []
        for start in range(0, len(ids), self.pagination_limit):
            data = {
                self.uri: {"id": {"any_": ids[start : start + self.pagination_limit]}},
                "limit": self.pagination_limit,
            }
            resp = self._post(f"{self.uri}/filter", data)
            if resp is None:
                break
            items.extend(resp.json())
        return items

    def get_count(self) -> Optional[int]:
        """
        Get the number of items from the endpoint's /count route.

        Returns:
            int: The count, or None if the request failed.
        """
        resp = self._post(f"{self.uri}/count", {})
        return None if resp is None else resp.json()


def _error_status(err: requests.exceptions.RequestException) -> str:
    if err.response is not None:
        return str(err.response.status_code)
    if isinstance(err, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(err, requests.exceptions.ConnectionError):
        return "connection_error"
    return "error"
