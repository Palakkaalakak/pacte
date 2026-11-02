"""Value an inventory against the item catalog."""
from __future__ import annotations

from dataclasses import dataclass

from blox_trade_finder.core.normalize import resolved_inventory_name
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


def value_inventory(
    inventory: Inventory, catalog: Catalog, basis: str = "gamersberg", custom_values: dict | None = None,
    site_maps: dict[str, dict[str, int]] | None = None,
) -> list[ValuedItem]:
    """`site_maps` (arbitrage.value_maps) adds each site's own prices, harvested from scanned
    listings, so the account can be valued on FantasyBlox/Trade Hub/... numbers too."""
    # Catalog names can carry stray whitespace (e.g. "Scarlet Ghost "), so key on stripped names.
    by_name = {i.name.strip().lower(): i for i in catalog.items}
    merged: dict[str, ValuedItem] = {}
    for entry in inventory.items:
        name = resolved_inventory_name(entry)
        item = by_name.get(name.strip().lower())
        key = name.strip().lower()
        merged_values = dict(item.values) if item else {}
        for site, m in (site_maps or {}).items():
            if m.get(key, 0) > 0:
                merged_values[site] = m[key]
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
