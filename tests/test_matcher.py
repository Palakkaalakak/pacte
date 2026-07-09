from collections import Counter
from datetime import datetime, timedelta, timezone

from blox_trade_finder.core.matcher import find_matches, is_feasible, passes_beli_balance
from blox_trade_finder.core.normalize import build_listings
from blox_trade_finder.models import Catalog, CatalogItem, Goals, Listing


def _listings(sample_catalog: Catalog, sample_trades_raw: list[dict]):
    return build_listings(sample_trades_raw, sample_catalog)


def test_is_feasible_true_when_inventory_covers_want(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listing = _listings(sample_catalog, sample_trades_raw)[0]  # wants Shadow
    assert is_feasible(listing, Counter({"shadow": 1}))


def test_is_feasible_false_when_inventory_missing_item(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listing = _listings(sample_catalog, sample_trades_raw)[0]
    assert not is_feasible(listing, Counter({"kitsune": 1}))


def test_is_feasible_false_when_quantity_insufficient(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listing = _listings(sample_catalog, sample_trades_raw)[0]
    assert not is_feasible(listing, Counter({"shadow": 0}))


def test_find_matches_excludes_infeasible_listings(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    matches = find_matches(listings, Counter({"kitsune": 5}), Goals(any_fair=True))
    assert matches == []


def test_find_matches_min_profit_filter(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"shadow": 1})

    passes = find_matches(listings, inv, Goals(min_profit=2_000_000))
    assert len(passes) == 1

    fails = find_matches(listings, inv, Goals(min_profit=3_000_000))
    assert len(fails) == 0


def test_find_matches_min_demand_filter(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"shadow": 1})

    assert len(find_matches(listings, inv, Goals(min_demand=6))) == 1
    assert len(find_matches(listings, inv, Goals(min_demand=7))) == 0


def test_find_matches_want_item_filter(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"shadow": 1})

    assert len(find_matches(listings, inv, Goals(want_item="Yeti"))) == 1
    assert len(find_matches(listings, inv, Goals(want_item="Dragon"))) == 0


def test_find_matches_want_item_accepts_list_matching_any(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"shadow": 1})

    # The one feasible listing gives Yeti -> matches because Yeti is in the list,
    # even though Dragon and Kitsune aren't in this trade.
    assert len(find_matches(listings, inv, Goals(want_item=["Dragon", "Yeti"]))) == 1
    assert len(find_matches(listings, inv, Goals(want_item=["Dragon", "Kitsune"]))) == 0


def _listing_giving_named_item(name: str) -> Listing:
    give_item = CatalogItem(id=1, name=name)
    want_item = CatalogItem(id=2, name="WantSide")
    return Listing(
        id="want-perm-test", source="test", url="u", poster_name="p", poster_rating=0,
        give=[give_item], want=[want_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )


def test_find_matches_want_item_includes_permanent_variant_by_default() -> None:
    listing = _listing_giving_named_item("Permanent Kitsune")
    inv = Counter({"wantside": 1})
    assert len(find_matches([listing], inv, Goals(want_item="Kitsune"))) == 1


def test_find_matches_want_item_excludes_permanent_variant_when_disabled() -> None:
    listing = _listing_giving_named_item("Permanent Kitsune")
    inv = Counter({"wantside": 1})
    assert find_matches([listing], inv, Goals(want_item="Kitsune", want_item_include_permanent=False)) == []


def test_find_matches_want_item_permanent_toggle_does_not_affect_exact_match() -> None:
    listing = _listing_giving_named_item("Kitsune")
    inv = Counter({"wantside": 1})
    assert len(find_matches([listing], inv, Goals(want_item="Kitsune", want_item_include_permanent=False))) == 1


def test_find_matches_want_item_list_is_case_insensitive(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"shadow": 1})
    assert len(find_matches(listings, inv, Goals(want_item=["dragon", "YETI"]))) == 1


def test_find_matches_any_fair_excludes_negative_delta(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"shadow": 1})
    # trade-open-fair has positive delta (5M received vs 2.9M given) -> passes any_fair
    assert len(find_matches(listings, inv, Goals(any_fair=True))) == 1


def _listing_with_values(id_: str, give_value: int, get_value: int) -> Listing:
    give_item = CatalogItem(id=1, name="GiveSide", values={"gamersberg": get_value})
    want_item = CatalogItem(id=2, name="WantSide", values={"gamersberg": give_value})
    return Listing(
        id=id_, source="test", url="u", poster_name="p", poster_rating=0,
        give=[give_item], want=[want_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )


def test_find_matches_ranks_by_absolute_delta_not_profit_pct() -> None:
    inv = Counter({"wantside": 1})
    # low_pct_high_delta: give 10M get 10.5M -> delta=500K, profit=+5%
    # high_pct_low_delta: give 1M get 1.1M -> delta=100K, profit=+10%
    low_pct_high_delta = _listing_with_values("low-pct-high-delta", give_value=10_000_000, get_value=10_500_000)
    high_pct_low_delta = _listing_with_values("high-pct-low-delta", give_value=1_000_000, get_value=1_100_000)

    matches = find_matches([high_pct_low_delta, low_pct_high_delta], inv, Goals(any_fair=True))

    assert [m.listing.id for m in matches] == ["low-pct-high-delta", "high-pct-low-delta"]


def test_find_matches_respects_limit(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"shadow": 1})
    matches = find_matches(listings, inv, Goals(limit=0))
    assert matches == []


def test_find_matches_any_bypasses_every_other_filter(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"shadow": 1})
    # Every one of these filters would normally reject the single feasible listing.
    goals = Goals(any=True, want_item="Dragon", min_profit=999_999_999, exclude_lose_wfl=True)
    assert len(find_matches(listings, inv, goals)) == 1


def test_find_matches_any_still_requires_feasibility(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listings = _listings(sample_catalog, sample_trades_raw)
    inv = Counter({"kitsune": 5})  # doesn't cover what the listing wants (shadow)
    assert find_matches(listings, inv, Goals(any=True)) == []


def _listing_with_beli(give_beli: int, want_beli: int) -> Listing:
    give_item = CatalogItem(id=1, name="GiveSide", beli_price=give_beli)
    want_item = CatalogItem(id=2, name="WantSide", beli_price=want_beli)
    return Listing(
        id="x", source="test", url="u", poster_name="p", poster_rating=0,
        give=[give_item], want=[want_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )


def test_passes_beli_balance_true_within_40_percent() -> None:
    # 1,000,000 vs 700,000 -> 30% difference, within the 40% cap
    assert passes_beli_balance(_listing_with_beli(give_beli=1_000_000, want_beli=700_000))


def test_passes_beli_balance_false_beyond_40_percent() -> None:
    # 1,000,000 vs 500,000 -> 50% difference, blocked
    assert not passes_beli_balance(_listing_with_beli(give_beli=1_000_000, want_beli=500_000))


def test_passes_beli_balance_true_at_exact_40_percent_boundary() -> None:
    assert passes_beli_balance(_listing_with_beli(give_beli=1_000_000, want_beli=600_000))


def test_passes_beli_balance_true_when_no_known_beli_price() -> None:
    # Both sides 0 (e.g. trading only Permanent variants) -> can't evaluate, don't block
    assert passes_beli_balance(_listing_with_beli(give_beli=0, want_beli=0))


def test_find_matches_excludes_listing_that_violates_beli_rule() -> None:
    # Poster gives something worth 1,000,000 Beli, wants something worth only
    # 100,000 Beli -> the game itself would refuse this trade.
    listing = _listing_with_beli(give_beli=1_000_000, want_beli=100_000)
    inv = Counter({"wantside": 1})
    assert find_matches([listing], inv, Goals(any=True)) == []


def _listing_with_trust(*, agreeing_sources: bool, beli_price: int) -> Listing:
    values = {"gamersberg": 100, "bloxfruit": 100} if agreeing_sources else {"gamersberg": 100}
    give_item = CatalogItem(id=1, name="GiveSide", values=values, beli_price=beli_price)
    want_item = CatalogItem(id=2, name="WantSide", values=values, beli_price=beli_price)
    return Listing(
        id="trust-test", source="test", url="u", poster_name="p", poster_rating=0,
        give=[give_item], want=[want_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )


def test_find_matches_min_confidence_filter() -> None:
    inv = Counter({"wantside": 1})

    trustworthy = _listing_with_trust(agreeing_sources=True, beli_price=100)
    assert len(find_matches([trustworthy], inv, Goals(min_confidence=50))) == 1

    # Only one value source and no Beli data to verify the 40% rule against ->
    # confidence stays low, shouldn't clear a 50 threshold.
    unverifiable = _listing_with_trust(agreeing_sources=False, beli_price=0)
    assert find_matches([unverifiable], inv, Goals(min_confidence=50)) == []


def _listing_with_age(hours_old: float) -> Listing:
    give_item = CatalogItem(id=1, name="GiveSide")
    want_item = CatalogItem(id=2, name="WantSide")
    return Listing(
        id="age-test", source="test", url="u", poster_name="p", poster_rating=0,
        give=[give_item], want=[want_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc) - timedelta(hours=hours_old),
    )


def test_find_matches_max_age_hours_filter() -> None:
    inv = Counter({"wantside": 1})

    fresh = _listing_with_age(hours_old=2)
    assert len(find_matches([fresh], inv, Goals(max_age_hours=24))) == 1

    stale = _listing_with_age(hours_old=48)
    assert find_matches([stale], inv, Goals(max_age_hours=24)) == []


def test_find_matches_max_age_hours_disabled_by_default() -> None:
    inv = Counter({"wantside": 1})
    ancient = _listing_with_age(hours_old=10_000)
    assert len(find_matches([ancient], inv, Goals())) == 1


def _listing_giving(name: str, count: int) -> Listing:
    want_item = CatalogItem(id=1, name="WantSide")
    give_items = [CatalogItem(id=2, name=name) for _ in range(count)]
    return Listing(
        id="qty-test", source="test", url="u", poster_name="p", poster_rating=0,
        give=give_items, want=[want_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )


def test_find_matches_max_qty_per_fruit_blocks_when_would_exceed_cap() -> None:
    # Already own 1 Dough; trade gives 1 more -> would own 2, over a cap of 1.
    inv = Counter({"wantside": 1, "dough": 1})
    listing = _listing_giving("Dough", count=1)
    assert find_matches([listing], inv, Goals(max_qty_per_fruit=1)) == []


def test_find_matches_max_qty_per_fruit_allows_up_to_cap() -> None:
    # Already own 1 Dough; trade gives 1 more -> would own 2, within a cap of 3.
    inv = Counter({"wantside": 1, "dough": 1})
    listing = _listing_giving("Dough", count=1)
    assert len(find_matches([listing], inv, Goals(max_qty_per_fruit=3))) == 1


def test_find_matches_max_qty_per_fruit_counts_multiple_copies_in_one_trade() -> None:
    # Own 0 Dough; trade gives 2 Dough in a single listing -> would own 2, over a cap of 1.
    inv = Counter({"wantside": 1})
    listing = _listing_giving("Dough", count=2)
    assert find_matches([listing], inv, Goals(max_qty_per_fruit=1)) == []


def test_find_matches_max_qty_per_fruit_applies_independently_per_fruit() -> None:
    # A cap of 1 lets you receive up to 1 of EACH distinct fruit, not a shared budget.
    want_item = CatalogItem(id=1, name="WantSide")
    give_items = [CatalogItem(id=2, name="Dough"), CatalogItem(id=3, name="Venom")]
    listing = Listing(
        id="qty-independent", source="test", url="u", poster_name="p", poster_rating=0,
        give=give_items, want=[want_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )
    inv = Counter({"wantside": 1})  # own none of either fruit yet
    assert len(find_matches([listing], inv, Goals(max_qty_per_fruit=1))) == 1


def test_find_matches_max_qty_per_fruit_disabled_by_default() -> None:
    inv = Counter({"wantside": 1, "dough": 50})
    listing = _listing_giving("Dough", count=1)
    assert len(find_matches([listing], inv, Goals())) == 1
