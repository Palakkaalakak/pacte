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


def test_parse_amount_and_editable_rows(tmp_path) -> None:
    from blox_trade_finder.core.overrides import default_rows, load_rows, overrides_from_rows, parse_amount, save_rows
    assert [parse_amount(x) for x in ("140m", "3.5B", "12k", "500000", "1,200", "x", "")] == [
        140_000_000, 3_500_000_000, 12_000, 500_000, 1_200, None, None]
    path = tmp_path / "cv.json"
    assert load_rows(path)[0]["item"] == "Dragon (West)"                # nothing saved -> defaults
    rows = default_rows()
    rows[0].update(value=4_000_000_000, use=True)                         # user edits West Dragon and ticks it
    rows.append({"item": "My Fruit", "demand": 12, "value": "2.5b", "use": True})
    save_rows([r for r in rows if isinstance(r["value"], int)], path)
    assert load_rows(path)[0]["value"] == 4_000_000_000
    ov = overrides_from_rows(rows)
    assert ov["dragon (west)"] == (10, 4_000_000_000) and ov["tiger"] == (9, 140_000_000)
    assert ov["my fruit"] == (10, 2_500_000_000)                          # demand clamped to 0-10, text value parsed
    assert "kitsune" not in ov                                            # not ticked -> not overridden
    assert overrides_from_rows([{"item": "X", "demand": 5, "value": "abc", "use": True}]) == {}
