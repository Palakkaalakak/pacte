from datetime import datetime, timezone

from blox_trade_finder.core.valuation import item_unit_value, value_inventory
from blox_trade_finder.models import Catalog, CatalogItem, Inventory, InventoryEntry


def _cat():
    items = [
        CatalogItem(id=1, name="Venom", values={"gamersberg": 100, "fruityblox": 50}),
        CatalogItem(id=2, name="Pain", values={"gamersberg": 10}),
    ]
    return Catalog(items=items, version=1, fetched_at=datetime.now(timezone.utc))


def test_value_inventory_totals_and_unknown() -> None:
    inv = Inventory(items=[InventoryEntry(name="Venom", qty=2), InventoryEntry(name="Pain"),
                           InventoryEntry(name="Mystery"), InventoryEntry(name="venom")])
    rows = value_inventory(inv, _cat())
    by = {r.name: r for r in rows}
    assert by["Venom"].qty == 3 and by["Venom"].total == 300
    assert by["Pain"].total == 10 and not by["Mystery"].known
    assert sum(r.total for r in rows) == 310


def test_average_basis() -> None:
    assert item_unit_value({"gamersberg": 100, "fruityblox": 50}, "average") == 75
    assert item_unit_value({}, "average") == 0


def test_catalog_name_with_trailing_space() -> None:
    cat = Catalog(items=[CatalogItem(id=3, name="Scarlet Ghost ", values={"gamersberg": 40})],
                  version=1, fetched_at=datetime.now(timezone.utc))
    rows = value_inventory(Inventory(items=[InventoryEntry(name="Scarlet Ghost")]), cat)
    assert rows[0].known and rows[0].total == 40
