"""Background live checker: rescans on an interval in its own thread so the UI
(and manual scans / chain searches) never block or cancel it.

Pure logic only — no Streamlit calls — so it is safe to run off the script
thread and easy to unit-test. The UI polls `snapshot()`.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from blox_trade_finder.core.chains import find_chains
from blox_trade_finder.core.normalize import inventory_counts
from blox_trade_finder.models import Goals, Inventory, Match
from blox_trade_finder.scan import run_scan
from blox_trade_finder.ui.table import format_value

logger = logging.getLogger(__name__)

NOTIFY_MAX_AGE_MINUTES = 10  # alarm / table only for listings this young


def _name_words(name: str) -> frozenset[str]:
    return frozenset(w for w in re.split(r"[^a-z0-9]+", name.lower()) if w and w != "permanent")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def notify_reason(match: Match, cfg: dict, max_age_minutes: float | None = NOTIFY_MAX_AGE_MINUTES) -> str | None:
    """Why `match` should sound the alarm (OR semantics), or None. Only
    listings posted within NOTIFY_MAX_AGE_MINUTES qualify. The threshold is
    PROFIT (received - given); "min_get_value" is a legacy saved-list key."""
    if max_age_minutes and (datetime.now(timezone.utc) - _aware(match.listing.created_at)).total_seconds() > max_age_minutes * 60:
        return None
    wanted = [_name_words(n) for n in cfg.get("items", []) if _name_words(n)]
    for item in match.listing.give:
        words = _name_words(item.name)
        if any(w <= words for w in wanted):
            return item.name
    min_value = cfg.get("min_profit") or cfg.get("min_get_value") or 0
    if min_value and match.delta >= min_value:
        return "+" + format_value(match.delta)
    return None


def is_scam(delta: int, profit_pct: float, cfg: dict | None) -> bool:
    """Too-good-to-be-true filter. `profit_pct` is already profit over what you
    GIVE (get/give - 100%), so +100% means you get double your item's value."""
    if not cfg:
        return False
    max_pct, max_abs = cfg.get("max_profit_pct"), cfg.get("max_profit")
    return bool((max_pct and profit_pct > max_pct) or (max_abs and delta > max_abs))


DEFAULT_BLOCKED_ITEMS = ("or", "add", "any", "upgrade", "downgrade")


def has_blocked_item(listing, cfg: dict | None) -> bool:
    """True if either side contains a placeholder like "Or"/"Upgrade"/"Any" —
    those listings aren't a definite, executable trade."""
    blocked = {b.strip().lower() for b in (cfg or {}).get("blocked_items", []) if b.strip()}
    return bool(blocked) and any(i.name.strip().lower() in blocked for i in (*listing.give, *listing.want))


def filter_listings(listings: list, cfg: dict | None) -> list:
    return [l for l in listings if not has_blocked_item(l, cfg)]


def filter_chains(chains: list, cfg: dict | None) -> list:
    return [c for c in chains if not is_scam(c.profit, c.profit_pct, cfg)]


def build_view(
    result, notify_cfg: dict, *, max_age_minutes: float | None, only_new: bool, seen: set[str] | None,
    scam_cfg: dict | None = None, notify_age_minutes: float | None = NOTIFY_MAX_AGE_MINUTES,
) -> tuple[dict, set[str]]:
    """Turn a ScanResult into a language-neutral view + the updated seen-set.

    Alarm hits are notify matches NOT in any earlier scan (first scan = silent
    baseline). With `only_new`, listings seen before are dropped from the table."""
    matches = result.matches
    too_old = 0
    if max_age_minutes:
        cut = max_age_minutes * 60
        now = datetime.now(timezone.utc)
        kept_age = [m for m in matches if (now - _aware(m.listing.created_at)).total_seconds() <= cut]
        too_old, matches = len(matches) - len(kept_age), kept_age
    excluded = 0
    if scam_cfg:
        kept = [
            m for m in matches
            if not is_scam(m.delta, m.profit_pct, scam_cfg) and not has_blocked_item(m.listing, scam_cfg)
        ]
        excluded, matches = len(matches) - len(kept), kept
    reasons = {id(m): notify_reason(m, notify_cfg, notify_age_minutes) for m in matches} if notify_cfg else {}
    keys = {id(m): f"{m.listing.source}:{m.listing.id}" for m in matches}
    new_hits = (
        {id(m) for m in matches if reasons.get(id(m)) and keys[id(m)] not in seen}
        if seen is not None else set()
    )
    new_seen = (seen or set()) | set(keys.values())
    if only_new and seen is not None:
        matches = [m for m in matches if keys[id(m)] not in seen]
    matches = sorted(matches, key=lambda m: id(m) not in new_hits)  # new hits on top
    rows = [{
        "notify": (("🆕🔔 " if id(m) in new_hits else "🔔 ") + reasons[id(m)]) if reasons.get(id(m)) else "",
        "source": m.listing.source,
        "give": ", ".join(i.name for i in m.listing.want),
        "get": ", ".join(i.name for i in m.listing.give),
        "delta": format_value(m.delta),
        "pct": f"{m.profit_pct:+.0%}",
        "demand": m.demand,
        "verdict": m.verdict.upper(),
        "conf": f"{m.confidence}%",
        "posted": m.listing.created_at,
        "url": m.listing.url,
        "is_new": id(m) in new_hits,
    } for m in matches]
    view = {
        "rows": rows, "count": len(rows), "new_hits": len(new_hits),
        "excluded": excluded, "too_old": too_old, "warnings": list(result.name_warnings), "ts": time.time(),
    }
    return view, new_seen


class LiveWorker:
    def __init__(
        self,
        *,
        inventory: Inventory,
        goals: Goals,
        sources: list[str],
        notify_cfg: dict,
        scam_cfg: dict | None = None,
        max_age_minutes: float | None,
        notify_age_minutes: float | None = NOTIFY_MAX_AGE_MINUTES,
        chain_cfg: dict | None,
        interval_seconds: int = 300,
        gb_max_pages: int | None = None,
        idle_timeout_seconds: int = 900,
        scan_fn: Callable = run_scan,
    ) -> None:
        self.inventory, self.goals, self.sources = inventory, goals, sources
        self.notify_cfg, self.max_age_minutes, self.chain_cfg = notify_cfg, max_age_minutes, chain_cfg
        self.scam_cfg = scam_cfg
        self.notify_age_minutes = notify_age_minutes
        self.interval, self.gb_max_pages = interval_seconds, gb_max_pages
        self.idle_timeout, self._scan_fn = idle_timeout_seconds, scan_fn
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="live-checker")
        self._seen: set[str] | None = None
        self._last_seen_by_ui = time.time()
        self.state: dict = {
            "view": None, "chains": None, "chains_ts": 0.0, "scans": 0, "alarm_seq": 0,
            "alarm_hits": 0, "last_scan_ts": None, "scanning": False, "error": None,
            "listings": None,
        }

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def snapshot(self) -> dict:
        """Called by the UI poller; doubles as the heartbeat that keeps us alive."""
        self._last_seen_by_ui = time.time()
        with self._lock:
            return dict(self.state)

    def _scan_once(self) -> None:
        with self._lock:
            self.state["scanning"] = True
        try:
            result = self._scan_fn(
                self.inventory, self.goals, sources=self.sources, deep=True,
                gb_max_pages=self.gb_max_pages,
            )
            view, self._seen = build_view(
                result, self.notify_cfg, max_age_minutes=self.max_age_minutes, only_new=True, seen=self._seen,
                scam_cfg=self.scam_cfg, notify_age_minutes=self.notify_age_minutes,
            )
            chains = None
            if self.chain_cfg is not None:
                chains = filter_chains(
                    find_chains(filter_listings(result.listings, self.scam_cfg), inventory_counts(self.inventory), **self.chain_cfg), self.scam_cfg
                )
            with self._lock:
                self.state.update(
                    view=view, scans=self.state["scans"] + 1, last_scan_ts=time.time(),
                    error=None, listings=(time.time(), result.listings),
                )
                if chains is not None:
                    self.state.update(chains=chains, chains_ts=time.time())
                if view["new_hits"]:
                    self.state["alarm_seq"] += 1
                    self.state["alarm_hits"] = view["new_hits"]
        except Exception as exc:  # keep looping — a failed scan must not kill the checker
            logger.exception("live scan failed")
            with self._lock:
                self.state.update(error=f"{type(exc).__name__}: {exc}", last_scan_ts=time.time())
        finally:
            with self._lock:
                self.state["scanning"] = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._scan_once()
            deadline = time.time() + self.interval
            while not self._stop.is_set() and time.time() < deadline:
                if time.time() - self._last_seen_by_ui > self.idle_timeout:
                    self._stop.set()  # browser tab gone — don't scan forever
                    return
                self._stop.wait(1)
