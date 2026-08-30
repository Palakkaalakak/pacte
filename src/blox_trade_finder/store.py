"""Persistent trade store for Gamersberg deep scans.

The Gamersberg trade feed is strictly newest-first with a locked page size of
12 and no server-side filters (verified live). A full deep scan of the feed
(hundreds of pages) is expensive, so we persist every trade we've ever seen
and, on subsequent scans, stop paginating once we hit pages made up entirely
of already-known trades.

Trades expire 7 days after posting (verified live); some deep-feed trades lack
an `expiresAt` field, so we fall back to created_at + 7 days.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from blox_trade_finder.cache import CACHE_DIR

logger = logging.getLogger(__name__)

STORE_PATH = CACHE_DIR / "gamersberg_trade_store.json"

# Verified live: Gamersberg trades carry expiresAt = createdAt + 7 days.
DEFAULT_TRADE_LIFETIME = timedelta(days=7)


def _parse_when(value: object) -> datetime | None:
    """Parse a Gamersberg timestamp: epoch milliseconds or ISO-8601 string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Epoch millis (the feed uses 13-digit values).
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


class TradeStore:
    """JSON-file-backed store of raw Gamersberg trades, keyed by trade id.

    NOTE: defines __len__, so an *empty* store is falsy — never use
    `store or TradeStore()` to default; use `if store is None`.
    """

    def __init__(self, path: Path = STORE_PATH) -> None:
        self.path = path
        self._trades: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._trades = {str(k): v for k, v in data.items() if isinstance(v, dict)}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("trade store at %s unreadable (%s) — starting empty", self.path, exc)
            self._trades = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self._trades, f)

    def known_ids(self) -> set[str]:
        return set(self._trades)

    def merge(self, trades: list[dict], *, save: bool = True) -> int:
        """Add/refresh trades; returns how many were previously unknown."""
        new = 0
        for t in trades:
            tid = str(t.get("id"))
            if tid not in self._trades:
                new += 1
            self._trades[tid] = t
        if save:
            self.save()
        return new

    def _expiry(self, trade: dict) -> datetime | None:
        expires = _parse_when(trade.get("expiresAt"))
        if expires is not None:
            return expires
        created = _parse_when(trade.get("createdAt"))
        if created is not None:
            return created + DEFAULT_TRADE_LIFETIME
        return None

    def prune(self, now: datetime | None = None) -> int:
        """Drop expired trades. Trades with no parsable timestamps are kept."""
        now = now or datetime.now(timezone.utc)
        before = len(self._trades)
        self._trades = {
            tid: t
            for tid, t in self._trades.items()
            if (expiry := self._expiry(t)) is None or expiry > now
        }
        removed = before - len(self._trades)
        if removed:
            self.save()
        return removed

    def active(self, now: datetime | None = None) -> list[dict]:
        """All non-expired trades currently in the store."""
        now = now or datetime.now(timezone.utc)
        return [
            t for t in self._trades.values()
            if (expiry := self._expiry(t)) is None or expiry > now
        ]

    def __len__(self) -> int:
        return len(self._trades)
