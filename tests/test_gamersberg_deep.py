from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import blox_trade_finder.sources.gamersberg as gb_module
from blox_trade_finder.sources.gamersberg import GamersbergSource
from blox_trade_finder.store import TradeStore

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _millis(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _trade(tid: str) -> dict:
    return {
        "id": tid,
        "createdAt": _millis(NOW - timedelta(hours=1)),
        "expiresAt": _millis(NOW + timedelta(days=6)),
    }


class _FakeResponse:
    def __init__(self, payload: list[dict]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> list[dict]:
        return self._payload


def _feed_responder(pages: dict[int, list[dict]], calls: list[int]):
    """Fake request_with_retry serving `pages`; records requested page numbers."""

    def _respond(client, method, url, *, params=None, rate_limiter=None):
        page = params["page"]
        calls.append(page)
        return _FakeResponse(pages.get(page, []))

    return _respond


def test_deep_first_scan_pages_to_feed_end(tmp_path: Path) -> None:
    pages = {1: [_trade("a"), _trade("b")], 2: [_trade("c")], 3: []}
    calls: list[int] = []
    store = TradeStore(tmp_path / "store.json")
    source = GamersbergSource()
    try:
        with patch.object(gb_module, "request_with_retry", _feed_responder(pages, calls)):
            trades = source.fetch_listings_raw(deep=True, store=store)
    finally:
        source.close()
    assert calls == [1, 2, 3]
    assert {t["id"] for t in trades} == {"a", "b", "c"}
    assert store.known_ids() == {"a", "b", "c"}


def test_deep_second_scan_stops_early_on_known_pages(tmp_path: Path) -> None:
    store = TradeStore(tmp_path / "store.json")
    store.merge([_trade(t) for t in ("a", "b", "c", "d", "e", "f")])

    # New trade on page 1, then three fully-known pages -> early stop after
    # KNOWN_PAGE_STREAK_TO_STOP=3, never touching page 5.
    pages = {
        1: [_trade("new1"), _trade("a")],
        2: [_trade("b"), _trade("c")],
        3: [_trade("d")],
        4: [_trade("e")],
        5: [_trade("never")],
    }
    calls: list[int] = []
    source = GamersbergSource()
    try:
        with patch.object(gb_module, "request_with_retry", _feed_responder(pages, calls)):
            trades = source.fetch_listings_raw(deep=True, store=store)
    finally:
        source.close()
    assert calls == [1, 2, 3, 4]
    ids = {t["id"] for t in trades}
    # "f" was never refetched but is served from the store; "never" untouched.
    assert "f" in ids
    assert "new1" in ids
    assert "never" not in ids


def test_deep_excludes_pruned_expired_trades(tmp_path: Path) -> None:
    store = TradeStore(tmp_path / "store.json")
    expired = {
        "id": "expired",
        "createdAt": _millis(NOW - timedelta(days=10)),
        "expiresAt": _millis(NOW - timedelta(days=3)),
    }
    store.merge([expired])
    pages = {1: [_trade("fresh")], 2: []}
    calls: list[int] = []
    source = GamersbergSource()
    try:
        with patch.object(gb_module, "request_with_retry", _feed_responder(pages, calls)):
            trades = source.fetch_listings_raw(deep=True, store=store)
    finally:
        source.close()
    ids = {t["id"] for t in trades}
    assert ids == {"fresh"}


def test_deep_respects_page_cap(tmp_path: Path) -> None:
    # Every page returns a unique new trade — without the cap it'd loop forever.
    pages = {n: [_trade(f"t{n}")] for n in range(1, 100)}
    calls: list[int] = []
    store = TradeStore(tmp_path / "store.json")
    source = GamersbergSource()
    try:
        with patch.object(gb_module, "request_with_retry", _feed_responder(pages, calls)), \
             patch.object(gb_module, "DEEP_MAX_TRADE_PAGES", 5):
            trades = source.fetch_listings_raw(deep=True, store=store)
    finally:
        source.close()
    assert calls == [1, 2, 3, 4, 5]
    assert len(trades) == 5


def test_deep_empty_store_passed_in_is_actually_used(tmp_path: Path) -> None:
    """Regression: an empty TradeStore is falsy (defines __len__), so a naive
    `store or TradeStore()` default would silently discard the caller's store.
    The passed-in (empty) store must receive the fetched trades."""
    pages = {1: [_trade("x")], 2: []}
    calls: list[int] = []
    store = TradeStore(tmp_path / "store.json")
    assert len(store) == 0 and not store  # precondition: falsy
    source = GamersbergSource()
    try:
        with patch.object(gb_module, "request_with_retry", _feed_responder(pages, calls)):
            source.fetch_listings_raw(deep=True, store=store)
    finally:
        source.close()
    assert store.known_ids() == {"x"}


def test_deep_reports_page_progress(tmp_path: Path) -> None:
    pages = {1: [_trade("a")], 2: [_trade("b")], 3: []}
    calls: list[int] = []
    progress: list[tuple[int, int]] = []
    store = TradeStore(tmp_path / "store.json")
    source = GamersbergSource()
    try:
        with patch.object(gb_module, "request_with_retry", _feed_responder(pages, calls)):
            source.fetch_listings_raw(
                deep=True, store=store, on_page_done=lambda page, new: progress.append((page, new))
            )
    finally:
        source.close()
    assert progress == [(1, 1), (2, 1), (3, 0)]
