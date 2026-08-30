from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from blox_trade_finder.store import DEFAULT_TRADE_LIFETIME, TradeStore

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _millis(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _trade(tid: str, created: datetime, expires: datetime | None = None) -> dict:
    t = {"id": tid, "createdAt": _millis(created)}
    if expires is not None:
        t["expiresAt"] = _millis(expires)
    return t


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    store = TradeStore(path)
    store.merge([_trade("a", NOW, NOW + timedelta(days=7))])
    reloaded = TradeStore(path)
    assert reloaded.known_ids() == {"a"}
    assert len(reloaded) == 1


def test_merge_counts_only_new(tmp_path: Path) -> None:
    store = TradeStore(tmp_path / "store.json")
    assert store.merge([_trade("a", NOW), _trade("b", NOW)]) == 2
    assert store.merge([_trade("a", NOW), _trade("c", NOW)]) == 1
    assert store.known_ids() == {"a", "b", "c"}


def test_prune_removes_expired(tmp_path: Path) -> None:
    store = TradeStore(tmp_path / "store.json")
    store.merge([
        _trade("old", NOW - timedelta(days=10), NOW - timedelta(days=3)),
        _trade("live", NOW, NOW + timedelta(days=7)),
    ])
    assert store.prune(NOW) == 1
    assert store.known_ids() == {"live"}
    assert [t["id"] for t in store.active(NOW)] == ["live"]


def test_missing_expires_falls_back_to_created_plus_lifetime(tmp_path: Path) -> None:
    store = TradeStore(tmp_path / "store.json")
    store.merge([
        _trade("expired_by_fallback", NOW - DEFAULT_TRADE_LIFETIME - timedelta(hours=1)),
        _trade("still_live", NOW - DEFAULT_TRADE_LIFETIME + timedelta(hours=1)),
    ])
    assert store.prune(NOW) == 1
    assert store.known_ids() == {"still_live"}


def test_corrupt_file_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text("{not json", encoding="utf-8")
    store = TradeStore(path)
    assert len(store) == 0
    store.merge([_trade("a", NOW)])
    assert json.loads(path.read_text(encoding="utf-8"))["a"]["id"] == "a"
