from blox_trade_finder.core.normalize import (
    build_listing,
    build_listings,
    check_inventory_names,
    inventory_counts,
    resolved_inventory_name,
)
from blox_trade_finder.models import Catalog, CatalogItem, Inventory, InventoryEntry


def test_build_listing_resolves_give_and_want(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    raw = next(t for t in sample_trades_raw if t["id"] == "trade-open-fair")
    listing = build_listing(raw, sample_catalog)
    assert listing is not None
    assert [i.name for i in listing.give] == ["Yeti"]
    assert [i.name for i in listing.want] == ["Shadow"]
    assert listing.url == "https://www.gamersberg.com/blox-fruits/trading/trade-open-fair"
    assert listing.calculator_url == (
        "https://www.gamersberg.com/blox-fruits/calculator?offer=92&request=71&game=blox-fruits"
    )
    assert listing.wfl == {"win": 3, "fair": 1, "lose": 0}


def test_build_listing_skips_completed(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    raw = next(t for t in sample_trades_raw if t["id"] == "trade-completed-skip")
    assert build_listing(raw, sample_catalog) is None


def test_build_listing_skips_expired(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    raw = next(t for t in sample_trades_raw if t["id"] == "trade-expired-skip")
    assert build_listing(raw, sample_catalog) is None


def test_build_listing_skips_unresolvable_items(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    raw = next(t for t in sample_trades_raw if t["id"] == "trade-unknown-item-skip")
    assert build_listing(raw, sample_catalog) is None


def test_build_listings_filters_down_to_usable_only(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = build_listings(sample_trades_raw, sample_catalog)
    assert [l.id for l in listings] == ["trade-open-fair"]


def test_check_inventory_names_silent_when_exact_match(sample_catalog: Catalog) -> None:
    inv = Inventory(items=[InventoryEntry(name="Kitsune")])
    assert check_inventory_names(inv, sample_catalog) == []


def test_check_inventory_names_warns_on_typo_with_suggestion(sample_catalog: Catalog) -> None:
    inv = Inventory(items=[InventoryEntry(name="Kitsun")])  # missing final 'e'
    warnings = check_inventory_names(inv, sample_catalog)
    assert len(warnings) == 1
    assert "Kitsun" in warnings[0]
    assert "Kitsune" in warnings[0]


def test_check_inventory_names_warns_on_accent_only_difference(sample_catalog: Catalog) -> None:
    from blox_trade_finder.models import CatalogItem

    catalog = sample_catalog.model_copy(
        update={"items": sample_catalog.items + [CatalogItem(id=999, name="Rose Quartz", values={})]}
    )
    inv = Inventory(items=[InventoryEntry(name="Rosé Quartz")])
    warnings = check_inventory_names(inv, catalog)
    assert len(warnings) == 1
    assert "accents" in warnings[0]


def test_check_inventory_names_warns_with_no_close_match(sample_catalog: Catalog) -> None:
    inv = Inventory(items=[InventoryEntry(name="Completely Made Up Item Xyz")])
    warnings = check_inventory_names(inv, sample_catalog)
    assert len(warnings) == 1
    assert "no close match" in warnings[0]


def test_inventory_counts_sums_quantities_case_insensitively() -> None:
    inv = Inventory(items=[
        InventoryEntry(name="Kitsune", qty=1),
        InventoryEntry(name="kitsune", qty=2),
        InventoryEntry(name="Shadow"),
    ])
    counts = inventory_counts(inv)
    assert counts["kitsune"] == 3
    assert counts["shadow"] == 1


def test_resolved_inventory_name_applies_permanent_prefix_when_variant_set() -> None:
    entry = InventoryEntry(name="Portal", variant="Permanent")
    assert resolved_inventory_name(entry) == "Permanent Portal"


def test_resolved_inventory_name_no_op_when_name_already_has_prefix() -> None:
    entry = InventoryEntry(name="Permanent Portal", variant="Permanent")
    assert resolved_inventory_name(entry) == "Permanent Portal"


def test_resolved_inventory_name_unchanged_without_permanent_variant() -> None:
    assert resolved_inventory_name(InventoryEntry(name="Portal")) == "Portal"
    assert resolved_inventory_name(InventoryEntry(name="Portal", variant="Physical")) == "Portal"


def test_inventory_counts_distinguishes_permanent_from_physical_via_variant() -> None:
    inv = Inventory(items=[
        InventoryEntry(name="Portal", qty=1),
        InventoryEntry(name="Portal", variant="Permanent", qty=2),
    ])
    counts = inventory_counts(inv)
    assert counts["portal"] == 1
    assert counts["permanent portal"] == 2


def test_check_inventory_names_uses_variant_resolved_name(sample_catalog: Catalog) -> None:
    catalog = sample_catalog.model_copy(
        update={"items": sample_catalog.items + [
            CatalogItem(id=998, name="Portal", values={"gamersberg": 100}),
            CatalogItem(id=999, name="Permanent Portal", values={"gamersberg": 200}),
        ]}
    )
    # variant="Permanent" resolves to "Permanent Portal", which exists -> no warning
    inv = Inventory(items=[InventoryEntry(name="Portal", variant="Permanent")])
    assert check_inventory_names(inv, catalog) == []
