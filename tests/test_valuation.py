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


def test_both_spellings_match_everywhere() -> None:
    from blox_trade_finder.core.normalize import check_inventory_names, inventory_counts
    cat = Catalog(items=[CatalogItem(id=3, name="Scarlet Ghost ", values={"gamersberg": 40})],
                  version=1, fetched_at=datetime.now(timezone.utc))
    assert cat.items[0].name == "Scarlet Ghost"
    for spelling in ("Scarlet Ghost", "Scarlet Ghost ", " scarlet ghost"):
        inv = Inventory(items=[InventoryEntry(name=spelling)])
        assert check_inventory_names(inv, cat) == []
        assert inventory_counts(inv)["scarlet ghost"] == 1


def test_highest_across_sites_inflation_adjusted() -> None:
    from blox_trade_finder.core.valuation import HIGHEST_ADJUSTED, HIGHEST_ADJUSTED_PLATFORM
    cat = Catalog(items=[CatalogItem(id=1, name="Venom", type="Natural", values={"gamersberg": 100})],
                  version=1, fetched_at=datetime.now(timezone.utc))
    inv = Inventory(items=[InventoryEntry(name="Venom")])
    site_maps = {"gamersberg": {"venom": 100}, "tradehub": {"venom": 130}, "bfvgg": {"venom": 110}}
    # tradehub runs 30% high on Natural fruits (n=5 items), bfvgg is level; platform-wide tradehub is 1.15
    inflation = {"Physical fruits": {"tradehub": (1.30, 5), "bfvgg": (1.00, 5)}}
    wide = {"tradehub": (1.15, 9), "bfvgg": (1.00, 9)}
    row = value_inventory(inv, cat, HIGHEST_ADJUSTED, None, site_maps, inflation, wide)[0]
    assert row.unit == 110                    # tradehub 130/1.30 = 100, gamersberg 100, bfvgg 110 -> highest is bfvgg
    row = value_inventory(inv, cat, HIGHEST_ADJUSTED_PLATFORM, None, site_maps, inflation, wide)[0]
    assert row.unit == 113                    # tradehub 130/1.15 = 113 now beats bfvgg's 110
    raw_highest = max(site_maps[s]["venom"] for s in site_maps)
    assert raw_highest == 130                 # without adjusting, the inflated site would have won
    # too few shared items to measure a level -> no adjustment
    thin = {"Physical fruits": {"tradehub": (1.30, 2)}}
    assert value_inventory(inv, cat, HIGHEST_ADJUSTED, None, site_maps, thin, {})[0].unit == 130
