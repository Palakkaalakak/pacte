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

from blox_trade_finder.core.arbitrage import SITE_VALUE_KEYS, find_item_arbitrage, item_gaps, platform_inflation, site_norms
from blox_trade_finder.core.chains import find_chains
from blox_trade_finder.core.normalize import inventory_counts
from blox_trade_finder.models import Goals, Inventory, Match
from blox_trade_finder.scan import run_scan
from blox_trade_finder.sources.extra_sites import EXTRA_SITES
from blox_trade_finder.ui.table import format_value

logger = logging.getLogger(__name__)

NOTIFY_MAX_AGE_MINUTES = 10  # alarm / table only for listings this young
FAST_REQUEST_INTERVAL = 0.25  # seconds between requests per site (interactive default is 1.0)
FAST_BFV_WORKERS = 6
BFV_LATEST_PAGE_SIZE = 25  # newest ads fetched per poll of bloxfruitsvalues' global feed
FAIL_STREAK_TO_REPORT = 6  # consecutive failed polls of one source before showing an error
BFV_POLLERS = 3  # overlapping pollers: one slow response never stalls polling
CA_MIN_GAP = 3.0  # min seconds between chain/arbitrage recomputes
FEED_MAX = 200  # newest offers kept on screen in live mode
MIN_LOOP_SECONDS = 0.5  # floor between scan starts, even in constant mode
FULL_REFRESH_EVERY = 10  # full bloxfruitsvalues refetch every N scans


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
    # Optional per-item loss tolerance: {"Venom": 50_000_000} = alert on Venom even
    # at a loss, but only up to 50M. Items without an entry alert at any profit.
    max_loss = [(_name_words(n), lim) for n, lim in (cfg.get("item_max_loss") or {}).items()]
    for item in match.listing.give:
        words = _name_words(item.name)
        if any(w <= words for w in wanted):
            limits = [lim for w, lim in max_loss if w <= words]
            if limits and match.delta < -min(limits):
                continue
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


def _is_excluded_permanent(name: str, allow: list[frozenset[str]]) -> bool:
    lower = name.strip().lower()
    if not lower.startswith("permanent "):
        return False
    base_words = _name_words(lower[len("permanent "):])
    return not any(a <= base_words for a in allow)


def has_blocked_item(listing, cfg: dict | None) -> bool:
    """True if either side contains a placeholder like "Or"/"Upgrade"/"Any" (not a definite
    trade), or - when `exclude_permanent` is on - a Permanent item that isn't in the allow list."""
    cfg = cfg or {}
    items = (*listing.give, *listing.want)
    blocked = {b.strip().lower() for b in cfg.get("blocked_items", []) if b.strip()}
    if blocked and any(i.name.strip().lower() in blocked for i in items):
        return True
    if cfg.get("exclude_permanent"):
        allow = [_name_words(a) for a in cfg.get("permanent_allow", []) if _name_words(a)]
        return any(_is_excluded_permanent(i.name, allow) for i in items)
    return False


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


def build_arb_view(listings: list, *, cfg: dict, inventory_counts, scam_cfg: dict | None) -> dict:
    """Arbitrage results as PLAIN rows (dicts/strings only). Plain data can never
    break the page after a redeploy changes a class, unlike stored objects."""
    listings = filter_listings(listings, scam_cfg)
    trades = find_item_arbitrage(
        listings, value_basis=cfg["value_basis"], min_pct=cfg["min_pct"],
        cross_site_only=cfg["cross_site_only"], max_age_minutes=cfg["max_age_minutes"],
        inventory_counts=inventory_counts if cfg["only_mine"] else None,
        judge_by_norm=cfg.get("judge_by_norm", False),
    )
    trades = [x for x in trades if not is_scam(x.profit, x.profit_pct, scam_cfg)]
    gaps = item_gaps(listings, min_ratio=cfg["min_ratio"])
    gap_cols = [k for k in SITE_VALUE_KEYS if any(k in g.values for g in gaps)]  # only sites that appear
    return {
        "ts": time.time(),
        "gaps": [{
            "Item": g.name,
            # amount (ratio): "Effective" removes the sites' usual price level for this kind of item
            # (the number that is actually an edge); "Raw" is the sites' numbers as published.
            "Effective gap": f"{format_value(g.gap)} ({g.ratio:.2f}x)",
            "Raw gap": f"{format_value(g.raw_gap)} ({g.raw_ratio:.2f}x)",
            "Higher on": g.higher_on, "Lower on": g.lower_on, "Class": g.cls,
            **{SITE_VALUE_KEYS[k]: (format_value(g.values[k]) if k in g.values else "") for k in gap_cols},
        } for g in gaps[:300]],
        "trades": [{
            "Item": x.item,
            "Buy: you pay": ", ".join(i.name for i in x.buy.want),
            "Buy on": x.buy.source,
            "Sell: you get": ", ".join(i.name for i in x.sell.give),
            "Sell on": x.sell.source,
            "Oldest leg": f"{x.oldest_minutes:.0f}m",
            "Cost": format_value(x.cost), "Revenue": format_value(x.revenue),
            "vs site norm": f"{x.vs_norm:.2f}x",
            "Profit": f"{format_value(x.profit)} ({x.profit_pct:+.0%})",
            "Buy link": x.buy.url, "Sell link": x.sell.url,
        } for x in trades[:300]],
    }


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
        arb_cfg: dict | None = None,
        custom_values: dict | None = None,
        scan_age_minutes: float | None = None,
        interval_seconds: int = 300,
        gb_max_pages: int | None = None,
        idle_timeout_seconds: int = 900,
        scan_fn: Callable = run_scan,
    ) -> None:
        self.inventory, self.goals, self.sources = inventory, goals, sources
        self.notify_cfg, self.max_age_minutes, self.chain_cfg = notify_cfg, max_age_minutes, chain_cfg
        self.scam_cfg = scam_cfg
        self.arb_cfg = arb_cfg
        self.custom_values = custom_values
        self.scan_age_minutes = scan_age_minutes  # how far back paging must go (None = everything)
        self.notify_age_minutes = notify_age_minutes
        self.interval, self.gb_max_pages = interval_seconds, gb_max_pages
        self.idle_timeout, self._scan_fn = idle_timeout_seconds, scan_fn
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="live-checker")
        self._seen: set[str] | None = None
        self._bfv_store: dict = {}
        self._scan_no = 0
        self._feed: list[dict] = []
        self._feed_urls: set[str] = set()
        self._last_full = 0
        self._proc_lock = threading.Lock()
        self._ca_lock = threading.Lock()
        self._ca_last = 0.0
        self._baselined: set[str] = set()
        self._src_listings: dict[str, list] = {}
        self._errors: dict[tuple, str] = {}
        self._fail_streak: dict[tuple, int] = {}
        self._gb_full_done = False
        self._bfv_thread: threading.Thread | None = None
        self._extra_threads: dict[str, threading.Thread] = {}
        self._last_seen_by_ui = time.time()
        self.state: dict = {
            "view": None, "chains": None, "chains_ts": 0.0, "scans": 0, "alarm_seq": 0,
            "alarm_hits": 0, "last_scan_ts": None, "scanning": False, "error": None,
            "listings": None, "arb": None,
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

    def _scan_once(self, sources: list[str] | None = None) -> None:
        """One scan. `sources` narrows it to a single site (constant mode runs the two
        sites in independent loops so the fast one never waits on the slow one)."""
        sources = sources or self.sources
        use_bfv = "bloxfruitsvalues" in sources
        use_gb = "gamersberg" in sources
        with self._lock:
            self.state["scanning"] = True
        try:
            # Speed: paced requests are 4x quicker than the interactive default, results are
            # never served from the 2-minute disk cache, and after one full bloxfruitsvalues
            # fetch we only re-read each item's NEWEST page (merged into a store). Chains and
            # arbitrage pair listings against the whole book, so while either is on we also
            # do a full bloxfruitsvalues refetch every FULL_REFRESH_EVERY scans.
            needs_book = self.chain_cfg is not None or self.arb_cfg is not None
            full = False
            if use_bfv:
                # Only chains/arbitrage need the whole book. Plain new-offer scanning starts
                # straight on the newest pages, so the first result arrives in seconds.
                full = needs_book and (
                    not self._bfv_store or self._scan_no - self._last_full >= FULL_REFRESH_EVERY
                )
                if full:
                    self._bfv_store = {}
                    self._last_full = self._scan_no
            self._scan_no += 1
            # Gamersberg: one page once the first full pass is done and we're in constant mode.
            gb_pages = 1 if (use_gb and self.interval == 0 and self._gb_full_done) else self.gb_max_pages
            result = self._scan_fn(
                self.inventory, self.goals, sources=sources, deep=True,
                gb_max_pages=gb_pages, custom_values=self.custom_values,
                fresh=True, catalog_fresh=False,
                request_interval=FAST_REQUEST_INTERVAL, bfv_workers=FAST_BFV_WORKERS,
                bfv_max_pages=None if full else 1, bfv_store=self._bfv_store,
                bfv_latest=None if full else BFV_LATEST_PAGE_SIZE,
                extra_latest=not needs_book, max_age_minutes=self.scan_age_minutes,
            )
            if use_gb:
                self._gb_full_done = True
            with self._proc_lock:  # the two constant-mode loops share seen/feed state
                # Each source gets its own silent baseline, otherwise the first bloxfruitsvalues
                # result would look "new" against Gamersberg's seen-set and alarm on everything.
                baseline = [src for src in sources if src not in self._baselined]
                seen = None if baseline else self._seen
                view, new_seen = build_view(
                    result, self.notify_cfg, max_age_minutes=self.max_age_minutes, only_new=True,
                    seen=seen, scam_cfg=self.scam_cfg, notify_age_minutes=self.notify_age_minutes,
                )
                self._seen = (self._seen or set()) | new_seen
                self._baselined.update(sources)
                # Keep new offers on screen: each scan only reports what is NEW, so without this
                # a hit would vanish at the next scan (seconds later in constant mode).
                hits_this_scan = view["new_hits"]
                this_scan = {r["url"] for r in view["rows"]}
                for row in view["rows"]:
                    if row["url"] not in self._feed_urls:
                        self._feed_urls.add(row["url"])
                        self._feed.insert(0, row)
                for row in self._feed:
                    row["is_new"] = row["is_new"] and row["url"] in this_scan
                del self._feed[FEED_MAX:]
                view = {**view, "rows": list(self._feed), "count": len(self._feed), "new_hits": hits_this_scan}
                for src in sources:
                    self._src_listings[src] = [l for l in result.listings if l.source == src]
                book = [l for ls in self._src_listings.values() for l in ls]
            chains = None
            arb = None
            # Chains/arbitrage run over the whole merged book. In constant mode six loops finish
            # scans many times a second, so recompute at most every CA_MIN_GAP seconds (the book
            # barely changes in between) instead of once per scan.
            with self._ca_lock:
                run_ca = (self.chain_cfg is not None or self.arb_cfg is not None) and (
                    time.time() - self._ca_last >= CA_MIN_GAP
                )
                if run_ca:
                    self._ca_last = time.time()
            if run_ca and self.chain_cfg is not None:
                chains = filter_chains(
                    find_chains(filter_listings(book, self.scam_cfg), inventory_counts(self.inventory), **self.chain_cfg),
                    self.scam_cfg,
                )
            if run_ca and self.arb_cfg is not None:
                arb = build_arb_view(
                    book, cfg=self.arb_cfg, inventory_counts=inventory_counts(self.inventory),
                    scam_cfg=self.scam_cfg,
                )
            with self._lock:
                if arb is not None:
                    self.state["arb"] = arb
                self._errors.pop(tuple(sources), None)
                self._fail_streak[tuple(sources)] = 0
                self.state.update(
                    view=view, scans=self.state["scans"] + 1, last_scan_ts=time.time(),
                    error="; ".join(self._errors.values()) or None, listings=(time.time(), book, self.scan_age_minutes),
                    site_counts={k: len(v) for k, v in self._src_listings.items()},
                )
                if chains is not None:
                    self.state.update(chains=chains, chains_ts=time.time())
                if view["new_hits"]:
                    self.state["alarm_seq"] += 1
                    self.state["alarm_hits"] = view["new_hits"]
        except Exception as exc:  # keep looping — a failed scan must not kill the checker
            logger.warning("live scan of %s failed: %s: %s", sources, type(exc).__name__, exc)
            with self._lock:
                # One timeout among many polls is normal for these sites; only surface an error
                # once a source has failed several polls in a row.
                key = tuple(sources)
                self._fail_streak[key] = self._fail_streak.get(key, 0) + 1
                if self._fail_streak[key] >= FAIL_STREAK_TO_REPORT:
                    self._errors[key] = f"{type(exc).__name__}: {exc}"
                self.state.update(error="; ".join(self._errors.values()) or None, last_scan_ts=time.time())
        finally:
            with self._lock:
                self.state["scanning"] = False

    def _idle_expired(self) -> bool:
        if time.time() - self._last_seen_by_ui > self.idle_timeout:
            self._stop.set()  # browser tab gone — don't scan forever
            return True
        return False

    def _bfv_poller(self) -> None:
        while not self._stop.is_set() and self.interval == 0:
            if self._idle_expired():
                return
            self._scan_once(["bloxfruitsvalues"])
            self._stop.wait(MIN_LOOP_SECONDS)

    def _bfv_loop(self) -> None:
        """Constant mode: bloxfruitsvalues on its own loops (it is the slow, erratic site, with
        responses ranging from 0.3 s to 10 s+), so Gamersberg's polling never waits for it. Several
        staggered pollers overlap, so one slow response doesn't delay the next poll. Exits when
        constant mode ends."""
        helpers = []
        for i in range(1, BFV_POLLERS):
            self._stop.wait(MIN_LOOP_SECONDS * i / BFV_POLLERS)
            t = threading.Thread(target=self._bfv_poller, daemon=True, name=f"live-bfv-{i}")
            t.start()
            helpers.append(t)
        self._bfv_poller()
        for t in helpers:
            t.join(timeout=1)

    def _extra_loop(self, site_id: str) -> None:
        """Constant mode: one independent loop per extra site, paced by that site's own
        poll gap (a multi-MB feed like Trade Hub shouldn't be hit every second)."""
        gap = max(EXTRA_SITES[site_id].poll_seconds, MIN_LOOP_SECONDS)
        while not self._stop.is_set() and self.interval == 0 and site_id in self.sources:
            if self._idle_expired():
                return
            self._scan_once([site_id])
            self._stop.wait(gap)

    def _loop(self) -> None:
        while not self._stop.is_set():
            constant = self.interval == 0
            if constant:
                # Gamersberg runs on this thread; every other site gets its own loop(s).
                if "bloxfruitsvalues" in self.sources and (self._bfv_thread is None or not self._bfv_thread.is_alive()):
                    self._bfv_thread = threading.Thread(target=self._bfv_loop, daemon=True, name="live-bfv")
                    self._bfv_thread.start()
                for sid in self.sources:
                    t = self._extra_threads.get(sid)
                    if sid in EXTRA_SITES and (t is None or not t.is_alive()):
                        t = threading.Thread(target=self._extra_loop, args=(sid,), daemon=True, name=f"live-{sid}")
                        self._extra_threads[sid] = t
                        t.start()
                if "gamersberg" in self.sources:
                    self._scan_once(["gamersberg"])
            else:
                self._scan_once()
            started = time.time()
            # interval 0 = constant mode: go again right away, with a floor so a fast scan can
            # never turn into a tight request loop.
            while not self._stop.is_set() and time.time() < started + max(self.interval, MIN_LOOP_SECONDS):
                if self._idle_expired():
                    return
                self._stop.wait(0.25 if self.interval == 0 else 1)
