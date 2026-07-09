import json
from pathlib import Path

from blox_trade_finder.core.normalize import _bfv_item_to_catalog_items, build_listing_bfv, build_listings_bfv
from blox_trade_finder.core.scoring import compute_values
from blox_trade_finder.models import Catalog, CatalogItem

FIXTURES = Path(__file__).parent / "fixtures"


def _sample_trades() -> list[dict]:
    with (FIXTURES / "bfv_trades_sample.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def test_build_listing_bfv_resolves_give_and_want_with_count_expansion() -> None:
    raw = next(t for t in _sample_trades() if t["id"] == "bfv-open-trade")
    listing = build_listing_bfv(raw)
    assert listing is not None
    assert listing.source == "bloxfruitsvalues"
    assert [i.name for i in listing.give] == ["Kitsune"]
    assert [i.name for i in listing.want] == ["Yeti", "Yeti"]  # count=2 expanded
    assert listing.url == "https://bloxfruitsvalues.com/trading/bfv-open-trade"
    assert listing.calculator_url is None
    assert listing.give[0].values == {"bloxfruitsvalues": 680_000_000}


def test_build_listing_bfv_skips_inactive() -> None:
    raw = next(t for t in _sample_trades() if t["id"] == "bfv-inactive-skip")
    assert build_listing_bfv(raw) is None


def test_build_listing_bfv_skips_expired() -> None:
    raw = next(t for t in _sample_trades() if t["id"] == "bfv-expired-skip")
    assert build_listing_bfv(raw) is None


def test_build_listings_bfv_filters_to_usable_only() -> None:
    listings = build_listings_bfv(_sample_trades())
    assert [l.id for l in listings] == ["bfv-open-trade"]


# Real raw item captured live from https://bloxfruitsvalues.com/trading/9c55031f-7dc6-49a6-8c51-b03c083db4fa
# — a Permanent Portal (worth ~2.4B) was being priced as the ~10M regular Portal before this fix.
_REAL_PERMANENT_PORTAL_ITEM = {
    "name": "Portal",
    "count": 1,
    "itemId": "17",
    "metadata": {
        "tier": "Legendary",
        "type": "Fruit",
        "value": "2400000000",
        "regValue": 10000000,
        "beliPrice": 1900000,
        "permTrend": "Overpaid",
        "permValue": 2400000000,
        "regDemand": 10,
        "permDemand": 9,
        "regTrend": "Overpaid",
        "robuxPrice": 2000,
        "__fruitType": "permanent",
        "rarity": "Legendary",
        "category": "Fruits",
    },
}


def test_bfv_item_uses_resolved_value_for_permanent_variant_not_regvalue() -> None:
    items = _bfv_item_to_catalog_items(_REAL_PERMANENT_PORTAL_ITEM)
    assert len(items) == 1
    item = items[0]
    assert item.values == {"bloxfruitsvalues": 2_400_000_000}
    assert item.name == "Permanent Portal"
    assert item.tags == ["Permanent"]
    assert item.demand == 9  # permDemand, not regDemand


def test_bfv_item_uses_regvalue_when_no_variant_signal() -> None:
    raw = {
        "name": "Kitsune", "count": 1, "itemId": "57",
        "metadata": {"regValue": 680_000_000, "regDemand": 10},
    }
    items = _bfv_item_to_catalog_items(raw)
    assert items[0].values == {"bloxfruitsvalues": 680_000_000}
    assert items[0].name == "Kitsune"  # no "Permanent " prefix without a variant signal
    assert items[0].demand == 10


def test_bfv_item_merges_real_gamersberg_values_when_catalog_given(sample_catalog: Catalog) -> None:
    # bloxfruitsvalues.com reports its own (possibly inflated) number for Yeti,
    # but Gamersberg's real catalog value must win when value_basis="gamersberg".
    raw = {
        "name": "Yeti", "count": 1, "itemId": "4",
        "metadata": {"value": "999999999", "regValue": 999_999_999, "regDemand": 1},
    }
    items = _bfv_item_to_catalog_items(raw, sample_catalog)
    assert items[0].values == {
        "bloxfruitsvalues": 999_999_999,
        "gamersberg": 5_000_000,       # from sample_catalog's real Yeti entry
        "fruityblox": 0,
        "bloxfruit": 4_800_000,
    }


def test_bfv_item_keeps_bloxfruitsvalues_only_when_not_in_gamersberg_catalog(sample_catalog: Catalog) -> None:
    raw = {
        "name": "Meme-Meme", "count": 1, "itemId": "999",
        "metadata": {"regValue": 6_950_000_000, "regDemand": 10},
    }
    items = _bfv_item_to_catalog_items(raw, sample_catalog)
    assert items[0].values == {"bloxfruitsvalues": 6_950_000_000}


def test_reported_bug_gamersberg_basis_shows_real_loss_not_bfv_inflated_profit(sample_catalog: Catalog) -> None:
    """Reproduces the exact reported issue: a bloxfruitsvalues.com trade offering
    Control x2 + Yeti for Green Lightning showed +40M profit (bloxfruitsvalues.com's
    own numbers) even though value_basis was "gamersberg" — because BFV items never
    carried a "gamersberg" value at all, so CatalogItem.value("gamersberg") silently
    fell back to bloxfruitsvalues.com's own number. With the real Gamersberg catalog
    values (Control 180M, Yeti 150M, Green Lightning 690M — verified live), this
    trade is actually a 180M loss."""
    catalog = Catalog(
        items=sample_catalog.items + [
            CatalogItem(id=101, name="Control", values={"gamersberg": 180_000_000}),
            CatalogItem(id=102, name="Green Lightning", values={"gamersberg": 690_000_000}),
        ],
        version=sample_catalog.version,
        fetched_at=sample_catalog.fetched_at,
    )
    raw_trade = {
        "id": "reported-bug-trade",
        "status": "active",
        "created_at": "2026-07-03T00:00:00.000Z",
        "expires_at": "2099-01-01T00:00:00.000Z",
        "user_username": "poster",
        "offered_items": [
            {"name": "Control", "count": 2, "itemId": "12", "metadata": {"value": "170000000", "regDemand": 10}},
            {"name": "Yeti", "count": 1, "itemId": "4", "metadata": {"value": "130000000", "regDemand": 8}},
        ],
        "requested_items": [
            {"name": "Green Lightning", "count": 1, "itemId": "58", "metadata": {"value": "430000000", "regDemand": 7}},
        ],
    }
    listing = build_listing_bfv(raw_trade, catalog)
    assert listing is not None

    _, _, delta_bloxfruitsvalues, _, _ = compute_values(listing, "bloxfruitsvalues")
    assert delta_bloxfruitsvalues == 40_000_000  # what the site's own numbers say

    give_value, get_value, delta_gamersberg, _, _ = compute_values(listing, "gamersberg")
    assert give_value == 690_000_000    # Green Lightning, real gamersberg value
    # Control x2 (real gamersberg 180M each) + Yeti (sample_catalog's gamersberg value, 5M)
    assert get_value == 180_000_000 * 2 + 5_000_000
    assert delta_gamersberg < 0  # a real loss, not the +40M bloxfruitsvalues suggested
