"""Shared HTTP helpers: one session with timeouts, retry/backoff and friendly errors."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings

log = logging.getLogger(__name__)


class ServiceError(Exception):
    """An external-service failure with a message that is safe to show the user."""

    def __init__(self, service: str, user_message: str, *, status: int | None = None):
        super().__init__(f"{service}: {user_message}")
        self.service = service
        self.user_message = user_message
        self.status = status


class RateLimitError(ServiceError):
    pass


def _build_session() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=0.8,                      # 0.8s, 1.6s, 3.2s
        status_forcelist=(500, 502, 503, 504),   # 429 is NOT retried blindly; we report it
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = "bilingual-assistant/1.0 (university project)"
    return session


_session = _build_session()


def _request(service: str, method: str, url: str, *, timeout: float | None = None, **kwargs) -> requests.Response:
    """Send a request and turn every failure into a ServiceError with a user-safe message."""
    started = time.perf_counter()
    try:
        resp = _session.request(method, url, timeout=timeout or settings.http_timeout, **kwargs)
    except requests.Timeout as e:
        raise ServiceError(service, "the service took too long to respond") from e
    except requests.ConnectionError as e:
        raise ServiceError(service, "could not connect (check your internet connection)") from e
    except requests.RequestException as e:
        raise ServiceError(service, "the request failed") from e

    log.info("http_request", extra={"service": service, "method": method, "status": resp.status_code,
                                     "ms": round((time.perf_counter() - started) * 1000)})
    if resp.status_code == 429:
        raise RateLimitError(service, "rate limit reached — please wait a minute and try again", status=429)
    if resp.status_code in (401, 403):
        raise ServiceError(service, "access denied (invalid API key or this data is not in your plan)",
                           status=resp.status_code)
    if resp.status_code == 402:
        raise ServiceError(service, "this feature needs a paid plan or more credits", status=402)
    if resp.status_code == 404:
        raise ServiceError(service, "the requested data was not found", status=404)
    if resp.status_code >= 400:
        raise ServiceError(service, f"the service returned an error (HTTP {resp.status_code})",
                           status=resp.status_code)
    return resp


def get_json(service: str, url: str, *, params: dict | None = None, headers: dict | None = None,
             timeout: float | None = None) -> Any:
    """GET a JSON document, translating every failure into a ServiceError."""
    resp = _request(service, "GET", url, params=params, headers=headers, timeout=timeout)
    try:
        return resp.json()
    except ValueError as e:
        raise ServiceError(service, "the service returned an unreadable response") from e


def post_for_bytes(service: str, url: str, *, json_body: dict, params: dict | None = None,
                   headers: dict | None = None, timeout: float | None = None) -> bytes:
    """POST JSON and return the raw response body (used for generated audio). Not retried
    automatically, because every call costs credits."""
    resp = _request(service, "POST", url, json=json_body, params=params, headers=headers, timeout=timeout)
    if not resp.content:
        raise ServiceError(service, "the service returned an empty response")
    return resp.content


class TTLCache:
    """Tiny thread-safe in-memory cache so we stay inside free-tier rate limits."""

    def __init__(self) -> None:
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: Any, ttl_seconds: float, factory: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > now:
                return hit[1]
        value = factory()  # outside the lock: network calls must not block other keys
        with self._lock:
            self._data[key] = (now + ttl_seconds, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class MinuteRateLimiter:
    """Client-side limiter (e.g. Football-Data.org free tier allows 10 requests/minute)."""

    def __init__(self, max_calls: int, period: float = 60.0):
        self.max_calls, self.period = max_calls, period
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self, service: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < self.period]
            if len(self._calls) >= self.max_calls:
                raise RateLimitError(service, "request limit for this minute reached — please try again shortly")
            self._calls.append(now)
