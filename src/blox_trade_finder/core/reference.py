"""Reference values: which site's numbers every comparison is measured against.

The app can use bloxfruitsvalues.com (default) or Gamersberg as the reference. Gamersberg's catalog is
always fetched (it names every item), but when the reference is bloxfruitsvalues.com each item in
every scanned listing gets bloxfruitsvalues.com's value for it (`apply_reference`), so matching,
profit, chains, arbitrage, gaps and account value all speak the same scale.
"""
from __future__ import annotations

import logging
import time

import httpx

from blox_trade_finder.http_client import USER_AGENT
from blox_trade_finder.models import CatalogItem, Listing

logger = logging.getLogger(__name__)

BFV = "bloxfruitsvalues"
GB = "gamersberg"
REFERENCES = (BFV, GB)
DEFAULT_REFERENCE = BFV
REFERENCE_LABELS = {BFV: "bloxfruitsvalues.com", GB: "Gamersberg"}

# Gamersberg's base name -> bloxfruitsvalues.com's name, where the two spell an item differently.
ALIASES: dict[str, str] = {
    "doghouse frame break": "doghouse (frame break)",
    "ember dragon": "ember west dragon",
    "galaxy kitsune": "galaxy empyrean kitsune",
    "glacier eagle": "eagle glacier",
    "matrix eagle": "eagle matrix",
    "requiem eagle": "eagle requiem",
    "magnet fruit": "magnet",
    "meme fruit": "meme-meme",
    "parrot skin": "parrot",
    "eclipse chromatic": "eclipse",
    "vibes (frame break)": "vibe (frame break)",
}

_current = DEFAULT_REFERENCE


def get_reference() -> str:
    """The reference every comparison is measured against (process-wide; the app sets it)."""
    return _current


def set_reference(name: str) -> None:
    global _current
    if name not in REFERENCES:
        raise ValueError(f"reference must be one of {REFERENCES}, got {name!r}")
    _current = name


_TABLE_TTL = 600
_cache: dict = {"at": 0.0, "table": {}}


def fetch_bfv_table(force: bool = False) -> dict[str, dict]:
    """bloxfruitsvalues.com's whole value list: {name (lower): {"reg", "perm", "reg_demand", "perm_demand"}}.
    Cached for 10 minutes; an empty dict (never an exception) if the site can't be reached."""
    if not force and _cache["table"] and time.time() - _cache["at"] < _TABLE_TTL:
        return _cache["table"]
    try:
        items: list[dict] = []
        with httpx.Client(base_url="https://bloxfruitsvalues.com", headers={"user-agent": USER_AGENT}, timeout=15.0) as c:
            page = 1
            while page <= 10:
                body = c.get("/api/v1/items/bloxfruits/all", params={"page": page, "limit": 100}).raise_for_status().json()
                items += body.get("items", [])
                if not (body.get("pagination") or {}).get("hasMore"):
                    break
                page += 1
        table = {}
        for it in items:
            m = it.get("metadata") or {}
            table[str(it["name"]).strip().lower()] = {
                "reg": int(m.get("regValue") or 0), "perm": int(m.get("permValue") or 0),
                "reg_demand": m.get("regDemand"), "perm_demand": m.get("permDemand"),
            }
        if table:
            _cache.update(at=time.time(), table=table)
        return table
    except Exception as exc:
        logger.warning("bloxfruitsvalues value table unavailable: %s: %s", type(exc).__name__, exc)
        return _cache["table"]


def bfv_value(name: str, table: dict[str, dict]) -> tuple[int, int | None]:
    """(value, demand) bloxfruitsvalues.com gives the item `name`, or (0, None) if it has no number."""
    lower = name.strip().lower()
    perm = lower.startswith("permanent ")
    base = lower[len("permanent "):] if perm else lower
    for key in (ALIASES.get(base, base), base):
        entry = table.get(key)
        if entry:
            v = entry["perm"] if perm else entry["reg"]
            if v > 0:
                return v, entry["perm_demand"] if perm else entry["reg_demand"]
    entry = table.get(lower)             # names that are their own entry, e.g. "Permanent Dragon Token"
    if entry and entry["reg"] > 0:
        return entry["reg"], entry["reg_demand"]
    return 0, None


def apply_reference(listings: list[Listing], reference: str, table: dict[str, dict] | None = None) -> list[Listing]:
    """For reference == bloxfruitsvalues.com: stamp every item with that site's value (and demand).
    Copies (the originals are shared catalog objects). Items the site doesn't price are left alone."""
    if reference != BFV:
        return listings
    table = fetch_bfv_table() if table is None else table
    if not table:
        return listings
    cache: dict[str, CatalogItem] = {}

    def stamp(item: CatalogItem) -> CatalogItem:
        hit = cache.get(item.name)
        if hit is None:
            value, demand = bfv_value(item.name, table)
            if value <= 0:
                hit = item
            else:
                update = {"values": {**item.values, BFV: value}}
                if demand is not None:
                    update["demand"] = int(demand)
                hit = item.model_copy(update=update)
            cache[item.name] = hit
        return hit

    return [l.model_copy(update={"give": [stamp(i) for i in l.give], "want": [stamp(i) for i in l.want]}) for l in listings]
