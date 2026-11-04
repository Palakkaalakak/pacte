"""Value an inventory against the item catalog."""
from __future__ import annotations

from dataclasses import dataclass

from blox_trade_finder.core.arbitrage import MIN_CLASS_ITEMS, SITE_VALUE_KEYS, item_class
from blox_trade_finder.core.normalize import resolved_inventory_name
from blox_trade_finder.core.reference import BFV, bfv_value, fetch_bfv_table, get_reference
from blox_trade_finder.models import Catalog, Inventory

BASES = ("gamersberg", "fruityblox", "bloxfruit")


@dataclass
class ValuedItem:
    name: str
    qty: int
    unit: int       # value of one copy (0 = unknown / not in catalog)
    known: bool

    @property
    def total(self) -> int:
        return self.unit * self.qty


def item_unit_value(values: dict[str, int], basis: str) -> int:
    """`basis` is a source id (catalog column or a site's own number) or "average" (mean of
    every source that prices the item, catalog columns and site numbers alike)."""
    if basis == "average":
        priced = [v for v in values.values() if v > 0]
        return round(sum(priced) / len(priced)) if priced else 0
    return values.get(basis, 0)


HIGHEST_ADJUSTED = "highest_adjusted"                    # per item class
HIGHEST_ADJUSTED_PLATFORM = "highest_adjusted_platform"  # one level per site, all classes pooled


def _highest_adjusted(values: dict[str, int], cls: str, basis: str, inflation: dict, wide: dict) -> int:
    """The highest value any scanned site gives the item, after removing that site's usual price
    level (vs Gamersberg) so a site that simply prices everything higher doesn't win by default."""
    best = 0.0
    for site, v in values.items():
        if site not in SITE_VALUE_KEYS or v <= 0:
            continue
        level, n = (wide.get(site, (1.0, 0)) if basis == HIGHEST_ADJUSTED_PLATFORM
                    else inflation.get(cls, {}).get(site, (1.0, 0)))
        best = max(best, v / level if (level and n >= MIN_CLASS_ITEMS) else float(v))
    return int(best)


def value_inventory(
    inventory: Inventory, catalog: Catalog, basis: str | None = None, custom_values: dict | None = None,
    site_maps: dict[str, dict[str, int]] | None = None,
    inflation: dict | None = None, wide_inflation: dict | None = None,
    bfv_table: dict | None = None,
) -> list[ValuedItem]:
    """`site_maps` (arbitrage.value_maps) adds each site's own prices, harvested from scanned
    listings, so the account can be valued on FantasyBlox/Trade Hub/... numbers too."""
    # Catalog names can carry stray whitespace (e.g. "Scarlet Ghost "), so key on stripped names.
    basis = basis or get_reference()          # default: whichever site is the reference
    by_name = {i.name.strip().lower(): i for i in catalog.items}
    # bloxfruitsvalues.com's own list prices (almost) every item, including ones no scanned ad mentions.
    needs_bfv = basis in (BFV, "average", HIGHEST_ADJUSTED, HIGHEST_ADJUSTED_PLATFORM) or bfv_table is not None
    table = (fetch_bfv_table() if bfv_table is None else bfv_table) if needs_bfv else {}
    merged: dict[str, ValuedItem] = {}
    for entry in inventory.items:
        name = resolved_inventory_name(entry)
        item = by_name.get(name.strip().lower())
        key = name.strip().lower()
        merged_values = dict(item.values) if item else {}
        for site, m in (site_maps or {}).items():
            if m.get(key, 0) > 0:
                merged_values[site] = m[key]
        if table:
            bv, _ = bfv_value(name, table)
            if bv > 0:
                merged_values[BFV] = bv
        if basis in (HIGHEST_ADJUSTED, HIGHEST_ADJUSTED_PLATFORM):
            cls = item_class(item) if item else "Physical fruits"
            unit = _highest_adjusted(merged_values, cls, basis, inflation or {}, wide_inflation or {})
        else:
            unit = item_unit_value(merged_values, basis) if (item or merged_values) else 0
        if item is None and unit > 0:
            item = True  # priced by a site even though Gamersberg's catalog lacks the name
        if custom_values and name.strip().lower() in custom_values:
            unit = custom_values[name.strip().lower()][1]
            item = item or True  # known via the override even if the catalog lacks it
        if key in merged:
            merged[key].qty += entry.qty
        else:
            merged[key] = ValuedItem(item.name if item is not None and item is not True else name, entry.qty, unit, item is not None and unit > 0)
    return sorted(merged.values(), key=lambda v: -v.total)
