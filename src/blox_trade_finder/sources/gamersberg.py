from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from blox_trade_finder.cache import get_or_fetch, peek
from blox_trade_finder.http_client import RateLimiter, make_client, request_with_retry
from blox_trade_finder.models import Catalog, CatalogItem
from blox_trade_finder.sources.base import TradeSource, ValueSource
from blox_trade_finder.store import TradeStore

logger = logging.getLogger(__name__)

BASE_URL = "https://www.gamersberg.com/service"
REFERER = "https://www.gamersberg.com/blox-fruits/trading"
GAME = "blox-fruits"

# Verified live: the feed kept returning ~12 new unique trades per page through
# page 30 with no sign of stopping, so this is a coverage/runtime trade-off,
# not a "the feed definitely ends here" boundary.
MAX_TRADE_PAGES = 60

# Deep-scan facts, verified live against the real API:
#   - page size is locked at 12 (limit/pageSize/size/per_page/count are ignored)
#   - there is NO server-side item filter
#   - the feed is strictly newest-first by createdAt
#   - the feed stays valid past page 400
#   - trades expire 7 days after posting (some deep trades LACK expiresAt)
# So a deep scan pages from 1 until it hits pages made up entirely of trades
# already in the persistent TradeStore — after the first full scan, subsequent
# scans only fetch the new head of the feed.
DEEP_MAX_TRADE_PAGES = 400
KNOWN_PAGE_STREAK_TO_STOP = 3

# If the live `version` jumps by more than this since our last cached fetch,
# the site's data model may have changed underneath us (plan: undocumented
# internal API risk) — warn rather than silently trust stale parsing.
VERSION_DRIFT_WARN_THRESHOLD = 20


def _parse_catalog_sse(raw: str) -> list[dict]:
    """Catalog stream is NDJSON-over-SSE: one item per `data:` line,
    terminated by a literal `data: [END]` line. Verified live this session —
    NOT a single JSON array (see plan section "Verified data shapes")."""
    items: list[dict] = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[END]":
            continue
        items.append(json.loads(payload))
    return items


def _to_catalog_item(raw: dict) -> CatalogItem:
    # `price` is the real in-game dealer Beli price. Verified live against known
    # values (Kitsune 8,000,000; Yeti 5,000,000; Buddha 1,200,000). Permanent
    # variants/skins/non-fruit items use -1 or 0 as a "not dealer-priced" sentinel
    # — clamp negatives to 0 so they read as "no known Beli price" everywhere else.
    beli_price = raw.get("price") or 0
    if beli_price < 0:
        beli_price = 0
    return CatalogItem(
        id=raw["id"],
        name=raw["name"],
        tags=raw.get("tags") or [],
        rarity=raw.get("rarity"),
        type=raw.get("type"),
        demand=raw.get("demand") or 0,
        trend=(raw.get("indicator") or "unknown").lower(),
        values={
            "gamersberg": raw.get("gamersbergvalue") or 0,
            "fruityblox": raw.get("fruitybloxvalue") or 0,
            "bloxfruit": raw.get("bloxfruitvalue") or 0,
        },
        robux_price=raw.get("robuxprice") or 0,
        beli_price=beli_price,
        image=raw.get("image"),
    )


class GamersbergSource(ValueSource, TradeSource):
    id = "gamersberg"
    ttl_seconds_catalog = 60 * 60
    ttl_seconds_trades = 2 * 60

    def __init__(self) -> None:
        self._client = make_client(BASE_URL, REFERER)
        # Own rate limiter, independent of any other source — a Gamersberg
        # request and a bloxfruitsvalues.com request are unrelated hosts and
        # shouldn't share a pacing clock. Also safe under threads: catalog and
        # trade-feed fetches may run concurrently against the same client.
        self._rate_limiter = RateLimiter()

    def close(self) -> None:
        self._client.close()

    def _fetch_version(self) -> int:
        resp = request_with_retry(
            self._client, "GET", f"/api/v1/game/v2/{GAME}/version", rate_limiter=self._rate_limiter
        )
        resp.raise_for_status()
        return resp.json()["version"]

    def _fetch_catalog_raw(self) -> dict:
        logger.info("gamersberg: fetching catalog via SSE GET /api/v1/game/v2/%s/all/info", GAME)
        self._rate_limiter.wait()
        with self._client.stream(
            "GET",
            f"/api/v1/game/v2/{GAME}/all/info",
            headers={"accept": "text/event-stream"},
            timeout=30.0,
        ) as resp:
            resp.raise_for_status()
            raw = "".join(resp.iter_text())
        items = _parse_catalog_sse(raw)
        version = self._fetch_version()
        logger.info("gamersberg: catalog fetched, %d items, version=%d", len(items), version)
        return {"items": items, "version": version, "fetched_at": datetime.now(timezone.utc).isoformat()}

    def fetch_catalog(self, *, fresh: bool = False) -> Catalog:
        cached_version = self._cached_version()
        data = get_or_fetch(
            "gamersberg_catalog", self.ttl_seconds_catalog, self._fetch_catalog_raw, fresh=fresh
        )
        if cached_version is not None and data["version"] - cached_version > VERSION_DRIFT_WARN_THRESHOLD:
            msg = (
                f"gamersberg data version jumped {cached_version} -> {data['version']}; "
                "site's data model may have changed."
            )
            logger.warning(msg)
            print(f"[warn] {msg}")
        return Catalog(
            items=[_to_catalog_item(i) for i in data["items"]],
            version=data["version"],
            fetched_at=data["fetched_at"],
        )

    def _cached_version(self) -> int | None:
        data = peek("gamersberg_catalog")
        return data.get("version") if data else None

    def fetch_listings_raw(
        self,
        *,
        item_names: list[str] | None = None,
        fresh: bool = False,
        deep: bool = False,
        store: TradeStore | None = None,
        on_page_done: Callable[[int, int], None] | None = None,
    ) -> list[dict]:
        # We always fetch the full feed rather than filtering per item (unlike
        # bloxfruitsvalues.com); item_names is accepted for interface
        # compatibility but unused.
        if deep:
            # NOT `store or TradeStore()`: TradeStore defines __len__, so an
            # empty store is falsy and would silently be swapped for the shared
            # default-path store — real bug caught by tests.
            if store is None:
                store = TradeStore()
            return self._fetch_deep(store, on_page_done=on_page_done)
        return get_or_fetch(
            "gamersberg_trades", self.ttl_seconds_trades, self._fetch_all_trade_pages, fresh=fresh
        )

    def _fetch_deep(
        self, store: TradeStore, *, on_page_done: Callable[[int, int], None] | None = None
    ) -> list[dict]:
        """Incremental deep scan: page the (newest-first) feed, stop after
        KNOWN_PAGE_STREAK_TO_STOP consecutive pages of already-stored trades,
        merge into the store, and return every active (non-expired) trade."""
        removed = store.prune()
        if removed:
            logger.debug("gamersberg deep: pruned %d expired trade(s) from store", removed)
        known = store.known_ids()
        fetched: dict[str, dict] = {}
        known_page_streak = 0
        page = 1
        while page <= DEEP_MAX_TRADE_PAGES:
            resp = request_with_retry(
                self._client, "GET", f"/api/v1/trade/list/all/{GAME}", params={"page": page},
                rate_limiter=self._rate_limiter,
            )
            resp.raise_for_status()
            body = resp.json()
            batch = body if isinstance(body, list) else list(body.values())

            unseen_this_fetch = 0
            unknown_to_store = 0
            for t in batch:
                tid = str(t.get("id"))
                if tid not in fetched:
                    unseen_this_fetch += 1
                    fetched[tid] = t
                if tid not in known:
                    unknown_to_store += 1
            logger.debug(
                "gamersberg deep: page %d -> %d trades (%d unseen, %d new to store)",
                page, len(batch), unseen_this_fetch, unknown_to_store,
            )
            if on_page_done is not None:
                on_page_done(page, unknown_to_store)

            if not batch or unseen_this_fetch == 0:
                break  # true end of feed (or the API started repeating itself)
            if unknown_to_store == 0:
                known_page_streak += 1
                if known_page_streak >= KNOWN_PAGE_STREAK_TO_STOP:
                    logger.debug(
                        "gamersberg deep: %d consecutive fully-known pages — stopping early",
                        known_page_streak,
                    )
                    break
            else:
                known_page_streak = 0
            page += 1
        else:
            logger.warning(
                "gamersberg deep: hit %d-page cap — feed may extend further", DEEP_MAX_TRADE_PAGES
            )

        new = store.merge(list(fetched.values()))
        active = store.active()
        logger.info(
            "gamersberg deep: fetched %d trade(s) across %d page(s), %d new to store, "
            "%d active total",
            len(fetched), min(page, DEEP_MAX_TRADE_PAGES), new, len(active),
        )
        return active

    def _fetch_all_trade_pages(self) -> list[dict]:
        seen: dict[str, dict] = {}
        page = 1
        while True:
            resp = request_with_retry(
                self._client, "GET", f"/api/v1/trade/list/all/{GAME}", params={"page": page},
                rate_limiter=self._rate_limiter,
            )
            resp.raise_for_status()
            body = resp.json()
            batch = body if isinstance(body, list) else list(body.values())
            if not batch:
                logger.debug("gamersberg: page %d empty, stopping", page)
                break
            new_count = 0
            for t in batch:
                if t["id"] not in seen:
                    seen[t["id"]] = t
                    new_count += 1
            logger.debug("gamersberg: page %d -> %d trades (%d new)", page, len(batch), new_count)
            if new_count == 0:
                break
            page += 1
            if page > MAX_TRADE_PAGES:  # sanity guard against an infinite loop on unexpected API behavior
                logger.warning(
                    "gamersberg: hit %d-page sanity cap while paginating trades — the feed was "
                    "still returning new unique trades at this point (confirmed live: still ~12 "
                    "new/page at page 30), so this cap likely still truncates real trades. Raise "
                    "MAX_TRADE_PAGES if you need full coverage.",
                    MAX_TRADE_PAGES,
                )
                break
        logger.info("gamersberg: fetched %d unique raw trades across %d page(s)", len(seen), page)
        return list(seen.values())
