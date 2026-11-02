"""Custom item values that replace the sites' numbers for chosen items."""
from __future__ import annotations

from blox_trade_finder.models import CatalogItem, Listing

# name -> (demand out of 10, value). Names are matched case-insensitively.
CUSTOM_VALUES: dict[str, tuple[int, int]] = {
    "Dragon (West)": (10, 3_500_000_000),
    "Dragon (East)": (10, 3_000_000_000),
    "Kitsune": (10, 600_000_000),
    "Magnet": (9, 700_000_000),
    "Control": (8, 165_000_000),
    "Tiger": (9, 140_000_000),
    "Yeti": (10, 130_000_000),
    "Gas": (9, 60_000_000),
    "Lightning": (7, 40_000_000),
    "Dough": (9, 30_000_000),
    "T-Rex": (7, 20_000_000),
    "Venom": (8, 20_000_000),
    "Buddha": (9, 10_000_000),
    "Gravity": (7, 10_000_000),
    "Pain": (7, 10_000_000),
    "Portal": (9, 10_000_000),
    "Spirit": (6, 10_000_000),
    "Mammoth": (6, 9_000_000),
    "Shadow": (5, 6_000_000),
}
DEFAULT_OVERRIDDEN = ("Tiger", "Yeti")  # on by default when the toggle is enabled


def build_overrides(names: list[str] | set[str]) -> dict[str, tuple[int, int]]:
    chosen = {n.strip().lower() for n in names}
    return {k.lower(): v for k, v in CUSTOM_VALUES.items() if k.lower() in chosen}


def override_item(item: CatalogItem, overrides: dict[str, tuple[int, int]]) -> CatalogItem:
    hit = overrides.get(item.name.strip().lower())
    if hit is None:
        return item
    demand, value = hit
    # Replace EVERY source's number, so whichever basis is selected uses the custom value.
    values = {k: value for k in item.values} or {}
    for k in ("gamersberg", "fruityblox", "bloxfruit", "bloxfruitsvalues",
              "fantasyblox", "tradehub", "tradebloxfruit", "bfvgg", "bloxvalues"):
        values[k] = value
    return item.model_copy(update={"values": values, "demand": demand})


def apply_overrides(listings: list[Listing], overrides: dict[str, tuple[int, int]] | None) -> list[Listing]:
    if not overrides:
        return listings
    out = []
    for lst in listings:
        out.append(lst.model_copy(update={
            "give": [override_item(i, overrides) for i in lst.give],
            "want": [override_item(i, overrides) for i in lst.want],
        }))
    return out
