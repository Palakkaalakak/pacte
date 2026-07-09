from datetime import datetime, timezone

from blox_trade_finder.core.normalize import build_listing
from blox_trade_finder.core.scoring import compute_confidence, compute_score, compute_values, compute_verdict
from blox_trade_finder.models import Catalog, CatalogItem, Listing


def _verdict_listing(give_value: int, get_value: int) -> Listing:
    """A listing where you'd give `give_value` (gamersberg basis) and receive
    `get_value` — used to test compute_verdict in isolation from real data."""
    give_item = CatalogItem(id=1, name="WantSide", values={"gamersberg": give_value})
    get_item = CatalogItem(id=2, name="GiveSide", values={"gamersberg": get_value})
    return Listing(
        id="v", source="test", url="u", poster_name="p", poster_rating=0,
        give=[get_item], want=[give_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )


def _listing(sample_catalog: Catalog, sample_trades_raw: list[dict]):
    raw = next(t for t in sample_trades_raw if t["id"] == "trade-open-fair")
    return build_listing(raw, sample_catalog)


def test_compute_values_delta_and_profit_pct(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listing = _listing(sample_catalog, sample_trades_raw)
    give_value, get_value, delta, profit_pct, demand = compute_values(listing, "gamersberg")
    assert give_value == 2_900_000   # Shadow, gamersberg basis
    assert get_value == 5_000_000    # Yeti, gamersberg basis
    assert delta == 2_100_000
    assert round(profit_pct, 4) == round(2_100_000 / 2_900_000, 4)
    assert demand == 6               # min demand of what you receive (Yeti)


def test_compute_values_falls_back_when_basis_is_zero(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listing = _listing(sample_catalog, sample_trades_raw)
    # Yeti has fruityblox=0 -> requesting fruityblox basis must fall back (bloxfruit=4_800_000)
    _, get_value, _, _, _ = compute_values(listing, "fruityblox")
    assert get_value == 4_800_000


def test_compute_values_handles_zero_give_value_without_crashing() -> None:
    from blox_trade_finder.models import CatalogItem, Listing
    from datetime import datetime, timezone

    free_item = CatalogItem(id=1, name="Free Thing", values={"gamersberg": 0, "fruityblox": 0, "bloxfruit": 0})
    got_item = CatalogItem(id=2, name="Got Thing", values={"gamersberg": 100, "fruityblox": 0, "bloxfruit": 0})
    listing = Listing(
        id="x", source="test", url="u", calculator_url="c", poster_name="p", poster_rating=0,
        give=[got_item], want=[free_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )
    give_value, get_value, delta, profit_pct, demand = compute_values(listing, "gamersberg")
    assert give_value == 0
    assert profit_pct == 0.0  # no division by zero


def test_confidence_lower_when_value_sources_disagree(sample_catalog: Catalog, sample_trades_raw: list[dict]) -> None:
    listing = _listing(sample_catalog, sample_trades_raw)
    confidence = compute_confidence(listing)
    assert 0 <= confidence <= 100
    # Shadow has a wide gamersberg/fruityblox spread -> shouldn't be maximal confidence
    assert confidence < 100


def test_score_rewards_higher_profit_pct() -> None:
    low = compute_score(delta=100, profit_pct=0.05, demand=5, wfl={"win": 1, "fair": 0, "lose": 0}, confidence=50)
    high = compute_score(delta=1000, profit_pct=0.50, demand=5, wfl={"win": 1, "fair": 0, "lose": 0}, confidence=50)
    assert high > low


def test_score_rewards_win_lean_over_lose_lean() -> None:
    win_leaning = compute_score(delta=0, profit_pct=0.1, demand=5, wfl={"win": 5, "fair": 0, "lose": 0}, confidence=50)
    lose_leaning = compute_score(delta=0, profit_pct=0.1, demand=5, wfl={"win": 0, "fair": 0, "lose": 5}, confidence=50)
    assert win_leaning > lose_leaning


def test_compute_verdict_win_when_receiving_much_more_than_giving() -> None:
    # give=100, get=200 -> r = (100-200)/200*100 = -50 -> win
    assert compute_verdict(_verdict_listing(give_value=100, get_value=200)) == "win"


def test_compute_verdict_loss_when_giving_much_more_than_receiving() -> None:
    # give=200, get=100 -> r = (200-100)/200*100 = +50 -> loss
    assert compute_verdict(_verdict_listing(give_value=200, get_value=100)) == "loss"


def test_compute_verdict_fair_within_25_percent_band() -> None:
    # give=110, get=100 -> r = (110-100)/110*100 = ~9.1% -> fair
    assert compute_verdict(_verdict_listing(give_value=110, get_value=100)) == "fair"


def test_compute_verdict_boundary_exactly_25_percent_is_fair() -> None:
    # give=100, get=75 -> r = (100-75)/100*100 = 25.0 exactly -> fair (inclusive)
    assert compute_verdict(_verdict_listing(give_value=100, get_value=75)) == "fair"


def test_compute_verdict_just_over_25_percent_is_loss() -> None:
    # give=100, get=74 -> r = 26.0 -> loss
    assert compute_verdict(_verdict_listing(give_value=100, get_value=74)) == "loss"


def test_compute_verdict_fair_when_both_sides_unknown() -> None:
    assert compute_verdict(_verdict_listing(give_value=0, get_value=0)) == "fair"


def test_compute_verdict_always_uses_gamersberg_value_ignoring_other_bases() -> None:
    # An item with only a bloxfruitsvalues price and no gamersberg price at all:
    # value("gamersberg") falls back to the only source available (bloxfruitsvalues),
    # so the verdict is still computable — but a listing with a REAL gamersberg
    # price on one side and none on the other must classify using gamersberg
    # numbers specifically, not whatever a caller might otherwise pass as "basis".
    give_item = CatalogItem(id=1, name="A", values={"gamersberg": 100})
    get_item = CatalogItem(id=2, name="B", values={"gamersberg": 100, "bloxfruitsvalues": 999_999_999})
    listing = Listing(
        id="v", source="test", url="u", poster_name="p", poster_rating=0,
        give=[get_item], want=[give_item], wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=datetime.now(timezone.utc),
    )
    # Both sides worth 100 in gamersberg value -> fair, regardless of the huge
    # bloxfruitsvalues number sitting on the same item.
    assert compute_verdict(listing) == "fair"
