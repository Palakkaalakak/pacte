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
    """`basis` is one of BASES or "average" (mean of the sources that price it)."""
    if basis == "average":
        priced = [values[b] for b in BASES if values.get(b, 0) > 0]
        return round(sum(priced) / len(priced)) if priced else 0
    return values.get(basis, 0)


def value_inventory(inventory: Inventory, catalog: Catalog, basis: str = "gamersberg") -> list[ValuedItem]:
    by_name = catalog.by_name
    merged: dict[str, ValuedItem] = {}
    for entry in inventory.items:
        name = resolved_inventory_name(entry)
        item = by_name.get(name.strip().lower())
        unit = item_unit_value(item.values, basis) if item else 0
        key = name.strip().lower()
        if key in merged:
            merged[key].qty += entry.qty
        else:
            merged[key] = ValuedItem(item.name if item else name, entry.qty, unit, item is not None and unit > 0)
    return sorted(merged.values(), key=lambda v: -v.total)
