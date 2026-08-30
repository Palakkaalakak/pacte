"""Shared scan pipeline used by the CLI, the Streamlit UI, and the watcher.

One entry point — run_scan() — fetches the selected sources concurrently,
normalizes their raw trades against the Gamersberg catalog, and matches them
against the user's inventory and goals.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from blox_trade_finder.core.matcher import find_matches
from blox_trade_finder.core.normalize import (
    build_listings,
    build_listings_bfv,
    check_inventory_names,
    inventory_counts,
)
from blox_trade_finder.models import Goals, Inventory, Match
from blox_trade_finder.sources.bloxfruitsvalues import BloxFruitsValuesSource
from blox_trade_finder.sources.gamersberg import GamersbergSource
from blox_trade_finder.store import TradeStore

logger = logging.getLogger(__name__)

VALID_SOURCES = ("gamersberg", "bloxfruitsvalues")


@dataclass
class ScanResult:
    matches: list[Match]
    name_warnings: list[str]
    gamersberg_raw_count: int = 0
    bfv_raw_count: int = 0
    listings_count: int = 0


@dataclass
class ScanProgress:
    """Optional progress callbacks. All fire from worker threads — keep them
    cheap and exception-safe on the caller side."""
    on_phase: Callable[[str], None] | None = None
    on_bfv_item_done: Callable[[str, int, int], None] | None = None  # (name, done, total)
    on_gb_page_done: Callable[[int, int], None] | None = None  # (page, new_to_store)


def _phase(progress: ScanProgress | None, name: str) -> None:
    if progress and progress.on_phase:
        progress.on_phase(name)


def run_scan(
    inventory: Inventory,
    goals: Goals,
    *,
    sources: list[str] | None = None,
    deep: bool = True,
    fresh: bool = False,
    store: TradeStore | None = None,
    progress: ScanProgress | None = None,
) -> ScanResult:
    """Fetch, normalize and match. `sources` defaults to all of VALID_SOURCES."""
    if sources is None:
        sources = list(VALID_SOURCES)
    unknown = [s for s in sources if s not in VALID_SOURCES]
    if unknown:
        raise ValueError(f"Unknown source(s): {unknown}. Valid: {list(VALID_SOURCES)}")
    use_gb = "gamersberg" in sources
    use_bfv = "bloxfruitsvalues" in sources

    gamersberg = GamersbergSource()
    bfv = BloxFruitsValuesSource()
    try:
        item_names = [entry.name for entry in inventory.items]

        def _fetch_gb() -> list[dict]:
            if not use_gb:
                return []
            if deep:
                gb_store = store if store is not None else TradeStore()
                return gamersberg.fetch_listings_raw(
                    fresh=fresh,
                    deep=True,
                    store=gb_store,
                    on_page_done=progress.on_gb_page_done if progress else None,
                )
            return gamersberg.fetch_listings_raw(fresh=fresh)

        def _fetch_bfv() -> list[dict]:
            if not (use_bfv and item_names):
                return []

            def _on_item_done(name: str, _count: list[int] = [0]) -> None:
                _count[0] += 1
                if progress and progress.on_bfv_item_done:
                    progress.on_bfv_item_done(name, _count[0], len(item_names))

            return bfv.fetch_listings_raw(
                item_names=item_names, fresh=fresh, on_item_done=_on_item_done
            )

        # The two hosts are unrelated (each source has its own rate limiter),
        # so fetch them concurrently; the (fast, usually cached) Gamersberg
        # catalog fetch happens on the main thread meanwhile.
        with ThreadPoolExecutor(max_workers=2) as executor:
            f_gb = executor.submit(_fetch_gb)
            f_bfv = executor.submit(_fetch_bfv)

            _phase(progress, "catalog")
            # Catalog always comes from Gamersberg regardless of trade sources —
            # it's the item/value database both normalizers resolve against.
            catalog = gamersberg.fetch_catalog(fresh=fresh)
            name_warnings = check_inventory_names(inventory, catalog)

            gamersberg_raw = f_gb.result()
            bfv_raw = f_bfv.result()

        _phase(progress, "matching")
        listings = build_listings(gamersberg_raw, catalog) + build_listings_bfv(bfv_raw, catalog)
        inv_counts = inventory_counts(inventory)
        matches = find_matches(listings, inv_counts, goals)
        logger.info(
            "scan: %d gamersberg raw, %d bfv raw, %d listings, %d matches",
            len(gamersberg_raw), len(bfv_raw), len(listings), len(matches),
        )
        return ScanResult(
            matches=matches,
            name_warnings=name_warnings,
            gamersberg_raw_count=len(gamersberg_raw),
            bfv_raw_count=len(bfv_raw),
            listings_count=len(listings),
        )
    finally:
        gamersberg.close()
        bfv.close()
