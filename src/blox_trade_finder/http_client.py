from __future__ import annotations

import threading
import time

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_MIN_INTERVAL_SECONDS = 1.0


class RateLimiter:
    """Keeps requests through this limiter to ~1/sec (plan section on ToS/rate-limit
    risk — these are undocumented internal APIs, be polite). One instance per
    source/host: two unrelated sites shouldn't share a pacing clock, and each
    source's requests (possibly from multiple threads) should still serialize
    against each other via the lock."""

    def __init__(self, min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS) -> None:
        self._min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request_at = time.monotonic()


def make_client(base_url: str, referer: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        headers={
            "user-agent": USER_AGENT,
            "origin": "https://www.gamersberg.com",
            "referer": referer,
        },
        timeout=20.0,
    )


def request_with_retry(
    client: httpx.Client, method: str, url: str, *, rate_limiter: RateLimiter, max_retries: int = 3, **kwargs
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        rate_limiter.wait()
        try:
            resp = client.request(method, url, **kwargs)
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"server error {resp.status_code}", request=resp.request, response=resp
                )
            return resp
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            time.sleep(2**attempt)
    assert last_exc is not None
    raise last_exc
