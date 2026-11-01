from datetime import datetime, timezone

from blox_trade_finder.core.overrides import apply_overrides, build_overrides
from blox_trade_finder.core.valuation import value_inventory
from blox_trade_finder.models import Catalog, CatalogItem, Inventory, InventoryEntry, Listing


def _item(n, v):
    return CatalogItem(id=1, name=n, demand=3, values={"gamersberg": v, "fruityblox": v})


def test_override_replaces_all_sources_and_demand() -> None:
    lst = Listing(id="1", source="g", url="u", poster_name="p", poster_rating=1.0,
                  give=[_item("Tiger", 500), _item("Dough", 7)], want=[_item("Yeti", 900)], wfl={},
                  created_at=datetime.now(timezone.utc))
    ov = build_overrides({"tiger", "Yeti"})
    out = apply_overrides([lst], ov)[0]
    assert out.give[0].values["gamersberg"] == 140_000_000 and out.give[0].demand == 9
    assert out.give[0].value("fruityblox") == 140_000_000
    assert out.give[1].values["gamersberg"] == 7          # not selected -> untouched
    assert out.want[0].value("gamersberg") == 130_000_000
    assert lst.give[0].values["gamersberg"] == 500        # original not mutated
    assert apply_overrides([lst], None) == [lst]


def test_value_inventory_uses_override() -> None:
    cat = Catalog(items=[_item("Tiger", 500)], version=1, fetched_at=datetime.now(timezone.utc))
    rows = value_inventory(Inventory(items=[InventoryEntry(name="Tiger", qty=2)]), cat, "gamersberg",
                           build_overrides({"Tiger"}))
    assert rows[0].total == 280_000_000
