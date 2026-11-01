from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import httpx

from blox_trade_finder.cache import get_or_fetch
from blox_trade_finder.http_client import RateLimiter, make_client, request_with_retry
from blox_trade_finder.sources.base import TradeSource

logger = logging.getLogger(__name__)

BASE_URL = "https://bloxfruitsvalues.com"
REFERER = "https://bloxfruitsvalues.com/trading"
GAME_TYPE = "bloxfruits"

# This site hosts 200k+ trade ads across all its supported games — paging through
# the full feed isn't feasible for a manual scan. Instead we run one server-side
# filtered query per inventory item (filter=<name>&scope=wants), same idea as
# searching "who wants what I own" directly, and cap pages per item so a scan
# with many inventory items stays a bounded number of requests.
PAGE_SIZE = 50
MAX_PAGES_PER_ITEM = 3
LIVE_PAGE_SIZE = 20
TTL_SECONDS = 2 * 60
# Items fetched concurrently; the shared RateLimiter still paces actual HTTP
# requests to ~1/sec, so this just removes idle thread-switch overhead rather
# than hammering the host harder.
MAX_WORKERS = 5


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class BloxFruitsValuesSource(TradeSource):
    id = "bloxfruitsvalues"
    ttl_seconds = TTL_SECONDS

    def __init__(self, request_interval: float = 1.0, max_workers: int = MAX_WORKERS) -> None:
        self._max_workers = max_workers
        self._client = make_client(BASE_URL, REFERER)
        # Own rate limiter — independent of Gamersberg's, so scanning both
        # sites concurrently doesn't cross-throttle two unrelated hosts.
        self._rate_limiter = RateLimiter(request_interval)
        # Fast (live) mode: a flaky request is retried quickly and then skipped — the next scan
        # is seconds away, so it isn't worth waiting 1s+2s+4s for one failing item.
        self._retry = {"max_retries": 2, "backoff_base": 0.25} if request_interval < 1.0 else {}

    def close(self) -> None:
        self._client.close()

    def fetch_listings_raw(
        self,
        *,
        item_names: list[str] | None = None,
        fresh: bool = False,
        on_item_done: Callable[[str], None] | None = None,
        max_pages: int | None = None,
    ) -> list[dict]:
        """`on_item_done(name)` is called once per item after it's been queried
        (whether it succeeded or was skipped) — lets the CLI show real
        per-item progress on the slowest step of a scan."""
        if not item_names:
            logger.info("bloxfruitsvalues: no item_names given, skipping (nothing to search for)")
            return []

        logger.info(
            "bloxfruitsvalues: querying %d inventory item(s): %s", len(item_names), item_names
        )
        def _fetch_one(name: str) -> list[dict] | None:
            try:
                # Partial (newest-page-only) fetches get their own cache key so they
                # can never be mistaken for a full multi-page result.
                suffix = f"_p{max_pages}" if max_pages else ""
                return get_or_fetch(
                    f"bfv_trades_{_slugify(name)}{suffix}",
                    self.ttl_seconds,
                    lambda n=name: self._fetch_for_name(n, max_pages) if max_pages else self._fetch_for_name(n),
                    fresh=fresh,
                )
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                # This is a real, observed failure mode: bloxfruitsvalues.com's
                # backend occasionally returns a transient 5xx for one query even
                # when the same query succeeds moments later. One bad item used
                # to crash the entire scan and lose every other item's results —
                # skip it and keep going instead.
                logger.warning(
                    "bloxfruitsvalues: '%s' failed after retries (%s) — skipping this item, "
                    "continuing with the rest of your inventory",
                    name, exc,
                )
                return None

        by_id: dict[str, dict] = {}
        by_id_lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(_fetch_one, name): name for name in item_names}
            for future in as_completed(futures):
                name = futures[future]
                trades = future.result() or []
                with by_id_lock:
                    new_count = sum(1 for t in trades if t["id"] not in by_id)
                    for t in trades:
                        by_id[t["id"]] = t
                logger.info(
                    "bloxfruitsvalues: '%s' -> %d trade ad(s) wanting it (%d new, %d already seen)",
                    name, len(trades), new_count, len(trades) - new_count,
                )
                if on_item_done is not None:
                    on_item_done(name)
        logger.info("bloxfruitsvalues: %d unique trade ads collected total", len(by_id))
        return list(by_id.values())

    def _fetch_for_name(self, name: str, max_pages: int | None = None) -> list[dict]:
        results: list[dict] = []
        page = 1
        while page <= (max_pages or MAX_PAGES_PER_ITEM):
            resp = request_with_retry(
                self._client,
                "GET",
                f"/api/v1/tradeads/{GAME_TYPE}/all",
                params={
                    "page": page,
                    # Newest-page polling only needs the latest handful of ads: a small page
                    # is ~5x less data per request than the full 50.
                    "pageSize": LIVE_PAGE_SIZE if max_pages == 1 else PAGE_SIZE,
                    "filter": name, "scope": "wants",
                },
                rate_limiter=self._rate_limiter, **self._retry,
            )
            resp.raise_for_status()
            body = resp.json()
            items = body.get("items") or []
            results.extend(items)
            logger.debug(
                "bloxfruitsvalues: '%s' page %d -> %d item(s), hasMore=%s, totalCount=%s",
                name, page, len(items), body.get("hasMore"), body.get("totalCount"),
            )
            if not body.get("hasMore"):
                break
            page += 1
        return results
