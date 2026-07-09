from __future__ import annotations

import difflib
import logging
import unicodedata
from collections import Counter
from datetime import datetime, timezone

from blox_trade_finder.models import Catalog, CatalogItem, Inventory, InventoryEntry, Listing

logger = logging.getLogger(__name__)

TRADING_URL_BASE = "https://www.gamersberg.com/blox-fruits/trading"
CALCULATOR_URL_BASE = "https://www.gamersberg.com/blox-fruits/calculator"
BFV_TRADING_URL_BASE = "https://bloxfruitsvalues.com/trading"


def _resolve_items(ids: list[int], catalog: Catalog) -> list:
    by_id = catalog.by_id
    resolved = []
    for item_id in ids:
        item = by_id.get(item_id)
        if item is not None:
            resolved.append(item)
    return resolved


def build_listing(raw: dict, catalog: Catalog) -> Listing | None:
    """One raw trade -> Listing, or None if it's unusable (completed, expired,
    or every item ID unresolved against the catalog)."""
    trade_id = raw.get("id", "?")
    if raw.get("completed"):
        logger.debug("gamersberg trade %s: skipped (already completed)", trade_id)
        return None

    expires_at = raw.get("expiresAt")
    if expires_at:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry < datetime.now(timezone.utc):
            logger.debug("gamersberg trade %s: skipped (expired %s)", trade_id, expires_at)
            return None

    give = _resolve_items(raw.get("sentItems") or [], catalog)
    want = _resolve_items(raw.get("receivedItems") or [], catalog)
    if not give or not want:
        logger.debug(
            "gamersberg trade %s: skipped (unresolved item ids — sentItems=%s receivedItems=%s "
            "resolved give=%d want=%d)",
            trade_id, raw.get("sentItems"), raw.get("receivedItems"), len(give), len(want),
        )
        return None

    trade_id = raw["id"]
    return Listing(
        id=trade_id,
        source="gamersberg",
        url=f"{TRADING_URL_BASE}/{trade_id}",
        calculator_url=(
            f"{CALCULATOR_URL_BASE}?offer={','.join(str(i.id) for i in give)}"
            f"&request={','.join(str(i.id) for i in want)}&game=blox-fruits"
        ),
        poster_name=(raw.get("sender") or {}).get("name", "unknown"),
        poster_rating=(raw.get("sender") or {}).get("averageRating", 0) or 0,
        give=give,
        want=want,
        wfl={
            "win": raw.get("wRating", 0) or 0,
            "fair": raw.get("fRating", 0) or 0,
            "lose": raw.get("lRating", 0) or 0,
        },
        created_at=raw["createdAt"],
        expires_at=expires_at,
    )


def build_listings(raw_trades: list[dict], catalog: Catalog) -> list[Listing]:
    listings = []
    for raw in raw_trades:
        listing = build_listing(raw, catalog)
        if listing is not None:
            listings.append(listing)
    logger.info(
        "gamersberg: %d raw trades -> %d usable listings (%d skipped)",
        len(raw_trades), len(listings), len(raw_trades) - len(listings),
    )
    return listings


def resolved_inventory_name(entry: InventoryEntry) -> str:
    """Gamersberg's catalog names Permanent fruit variants as a genuinely
    different item — 'Permanent Portal' vs 'Portal' are two separate catalog
    entries with different values/tags. If you set variant="Permanent" and
    your `name` doesn't already carry that prefix, apply it here so matching
    targets the correct catalog entry instead of silently matching the
    Physical version. Writing the full name yourself (e.g. "Permanent
    Portal") works exactly the same either way.

    Known limitation: bloxfruitsvalues.com does NOT distinguish these at all
    — its trade ads use a single shared item name/id for both variants with
    both values attached to the same entry, and don't say which one a given
    trade actually offers. This prefixing only ever changes which name is
    matched against Gamersberg-sourced listings."""
    variant = (entry.variant or "").strip().lower()
    if variant == "permanent" and not entry.name.lower().startswith("permanent "):
        return f"Permanent {entry.name}"
    return entry.name


def inventory_counts(inventory: Inventory) -> Counter[str]:
    """Multiset of owned items keyed by lowercased name, variant-resolved."""
    counts: Counter[str] = Counter()
    for entry in inventory.items:
        counts[resolved_inventory_name(entry).lower()] += entry.qty
    return counts


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def check_inventory_names(inventory: Inventory, catalog: Catalog) -> list[str]:
    """An inventory entry whose name doesn't exactly match a catalog item is
    silently invisible to matching (feasibility only checks exact lowercased
    names) — with no error, just fewer results. This surfaces that at load
    time instead of leaving the user to wonder why nothing was found."""
    warnings: list[str] = []
    by_name = catalog.by_name
    for entry in inventory.items:
        display_name = resolved_inventory_name(entry)
        name_lower = display_name.lower()
        if name_lower in by_name:
            continue

        normalized = _strip_accents(name_lower)
        accent_match = next(
            (n for n in by_name if _strip_accents(n) == normalized and n != name_lower), None
        )
        if accent_match:
            warnings.append(
                f"'{display_name}' isn't an exact catalog name (only differs by accents from "
                f"'{by_name[accent_match].name}') — this item won't be matched. Rename it to "
                f"the exact catalog name."
            )
            continue

        close = difflib.get_close_matches(name_lower, by_name.keys(), n=3, cutoff=0.6)
        if close:
            suggestions = ", ".join(f"'{by_name[c].name}'" for c in close)
            warnings.append(
                f"'{display_name}' not found in catalog — this item won't be matched. "
                f"Did you mean: {suggestions}?"
            )
        else:
            warnings.append(
                f"'{display_name}' not found in catalog and no close match — this item won't be "
                f"matched. Check exact spelling with --list-catalog."
            )
    for w in warnings:
        logger.warning("inventory name check: %s", w)
    return warnings


def _bfv_item_to_catalog_items(raw_item: dict, gamersberg_catalog: Catalog | None = None) -> list[CatalogItem]:
    """Unlike Gamersberg, bloxfruitsvalues.com embeds full item value/demand
    metadata directly on each trade-ad item — no separate catalog fetch needed.

    bloxfruitsvalues.com stores BOTH the regular/Physical and Permanent
    value/demand/trend on the SAME item entry (e.g. Portal carries both
    regValue=10,000,000 and permValue=2,400,000,000). It sometimes marks
    which variant a specific trade item actually is via a hidden
    `metadata.__fruitType` field, and pre-resolves that variant's number into
    `metadata.value`. Verified live on a real trade: __fruitType="permanent"
    with value="2400000000", matching permValue exactly. This was a real bug
    — we used to always take regValue, so an offer of a Permanent Portal
    (worth ~2.4B) was being priced as if it were the ~10M regular Portal,
    making the trade look like a wildly, implausibly good deal. Prefer
    `value` (site's own resolved number) when present; fall back to regValue
    when the site gives no variant signal at all for that item.

    IMPORTANT: this item's `values` dict only ever gets a "bloxfruitsvalues"
    key from the site's own data — it never has "gamersberg". This was a real
    bug: requesting value_basis="gamersberg" for a bloxfruitsvalues-sourced
    trade silently fell back to the site's own self-reported number (via
    CatalogItem.value()'s generic fallback) instead of an actual Gamersberg
    price, even though the item usually exists in Gamersberg's own catalog
    under the same name. If `gamersberg_catalog` is given, look the item up by
    its final (variant-resolved) name and merge in the real gamersberg/
    fruityblox/bloxfruit values so value_basis="gamersberg" means what it
    says for these trades too."""
    meta = raw_item.get("metadata") or {}
    count = raw_item.get("count") or 1
    try:
        item_id = int(raw_item.get("itemId") or 0)
    except (TypeError, ValueError):
        item_id = 0

    fruit_type = str(meta.get("__fruitType") or "").lower()
    is_permanent = fruit_type == "permanent"

    raw_value = meta.get("value")
    if raw_value is not None:
        try:
            value = int(float(raw_value))
        except (TypeError, ValueError):
            value = meta.get("regValue") or 0
    elif is_permanent:
        value = meta.get("permValue") or meta.get("regValue") or 0
    else:
        value = meta.get("regValue") or 0

    demand = (meta.get("permDemand") if is_permanent else meta.get("regDemand")) or 0
    trend = str((meta.get("permTrend") if is_permanent else meta.get("regTrend")) or "unknown").lower()

    name = raw_item.get("name", "Unknown Item")
    if is_permanent and not name.lower().startswith("permanent "):
        name = f"Permanent {name}"

    values = {"bloxfruitsvalues": value}
    if gamersberg_catalog is not None:
        gamersberg_item = gamersberg_catalog.by_name.get(name.lower())
        if gamersberg_item is not None:
            values.update(gamersberg_item.values)

    item = CatalogItem(
        id=item_id,
        name=name,
        tags=["Permanent"] if is_permanent else [t for t in [meta.get("category"), meta.get("type")] if t],
        rarity=meta.get("rarity"),
        type=meta.get("type"),
        demand=demand,
        trend=trend,
        values=values,
        robux_price=meta.get("robuxPrice") or 0,
        beli_price=meta.get("beliPrice") or 0,  # real in-game dealer price, 0 for non-fruit items
        image=raw_item.get("image"),
    )
    return [item] * max(1, count)


def build_listing_bfv(raw: dict, gamersberg_catalog: Catalog | None = None) -> Listing | None:
    """One raw bloxfruitsvalues.com trade ad -> Listing, or None if unusable
    (inactive, expired, or missing an offered/requested side). Pass the
    Gamersberg catalog so items get cross-populated with real gamersberg/
    fruityblox/bloxfruit values (see _bfv_item_to_catalog_items)."""
    trade_id = raw.get("id", "?")
    if raw.get("status") != "active":
        logger.debug("bloxfruitsvalues trade %s: skipped (status=%s)", trade_id, raw.get("status"))
        return None

    expires_at = raw.get("expires_at")
    if expires_at:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry < datetime.now(timezone.utc):
            logger.debug("bloxfruitsvalues trade %s: skipped (expired %s)", trade_id, expires_at)
            return None

    give: list[CatalogItem] = []
    for raw_item in raw.get("offered_items") or []:
        give.extend(_bfv_item_to_catalog_items(raw_item, gamersberg_catalog))
    want: list[CatalogItem] = []
    for raw_item in raw.get("requested_items") or []:
        want.extend(_bfv_item_to_catalog_items(raw_item, gamersberg_catalog))
    if not give or not want:
        logger.debug("bloxfruitsvalues trade %s: skipped (empty offered or requested side)", trade_id)
        return None

    trade_id = raw["id"]
    return Listing(
        id=trade_id,
        source="bloxfruitsvalues",
        url=f"{BFV_TRADING_URL_BASE}/{trade_id}",
        calculator_url=None,
        poster_name=raw.get("user_username") or raw.get("userName") or "unknown",
        poster_rating=0.0,  # this site doesn't expose a poster reputation score in the trade-ad payload
        give=give,
        want=want,
        wfl={"win": 0, "fair": 0, "lose": 0},  # no WFL community-vote system on this site
        created_at=raw["created_at"],
        expires_at=expires_at,
    )


def build_listings_bfv(raw_trades: list[dict], gamersberg_catalog: Catalog | None = None) -> list[Listing]:
    listings = []
    for raw in raw_trades:
        listing = build_listing_bfv(raw, gamersberg_catalog)
        if listing is not None:
            listings.append(listing)
    logger.info(
        "bloxfruitsvalues: %d raw trade ads -> %d usable listings (%d skipped)",
        len(raw_trades), len(listings), len(raw_trades) - len(listings),
    )
    return listings
