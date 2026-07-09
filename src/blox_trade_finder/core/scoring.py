from __future__ import annotations

from datetime import datetime, timezone

from blox_trade_finder.models import CatalogItem, Listing, ValueBasis


def compute_values(listing: Listing, basis: ValueBasis) -> tuple[int, int, int, float, int]:
    """Returns (give_value, get_value, delta, profit_pct, demand).

    You give `listing.want`, you receive `listing.give` (plan section 4, step 1:
    you take the counter-side of the poster's offer)."""
    give_value = sum(item.value(basis) for item in listing.want)
    get_value = sum(item.value(basis) for item in listing.give)
    delta = get_value - give_value
    profit_pct = (delta / give_value) if give_value > 0 else 0.0
    demand = min((item.demand for item in listing.give), default=0)
    return give_value, get_value, delta, profit_pct, demand


def compute_verdict(listing: Listing) -> str:
    """Real classification algorithm used by Gamersberg's own calculator,
    reverse-engineered from its client JS bundle: r = (give - get) /
    max(give, get) * 100, then "fair" if -25 <= r <= 25, else "loss" (r > 25,
    you're giving more than you get) or "win" (r < -25, you're getting more
    than you give).

    This ALWAYS uses gamersberg's own recorded value for both sides — never
    whatever `value_basis` the user picked for ranking/profit — because that's
    what Gamersberg's own calculator uses. It's computed here ourselves (not
    fetched from their site), using their exact formula, so the numbers match
    what their calculator would show for the same trade."""
    give_value = sum(item.value("gamersberg") for item in listing.want)
    get_value = sum(item.value("gamersberg") for item in listing.give)
    if give_value <= 0 and get_value <= 0:
        return "fair"
    r = (give_value - get_value) / max(give_value, get_value) * 100
    if -25 <= r <= 25:
        return "fair"
    return "loss" if r > 25 else "win"


def _value_agreement(items: list[CatalogItem]) -> float:
    """0..1, how well the 3 value sources agree for the items involved.
    1.0 = perfect agreement, lower = sources disagree or are missing data."""
    if not items:
        return 0.5
    scores = []
    for item in items:
        nonzero = [v for v in item.values.values() if v > 0]
        if len(nonzero) < 2:
            scores.append(0.5)  # only one source has data — can't cross-check
            continue
        spread = (max(nonzero) - min(nonzero)) / max(nonzero)
        scores.append(max(0.0, 1.0 - spread))
    return sum(scores) / len(scores)


def _freshness(listing: Listing) -> float:
    """0..1, fraction of the listing's lifetime remaining."""
    if listing.expires_at is None:
        return 0.5
    created = listing.created_at if isinstance(listing.created_at, datetime) else datetime.fromisoformat(str(listing.created_at))
    expires = listing.expires_at if isinstance(listing.expires_at, datetime) else datetime.fromisoformat(str(listing.expires_at))
    now = datetime.now(timezone.utc)
    total = (expires - created).total_seconds()
    if total <= 0:
        return 0.5
    remaining = (expires - now).total_seconds()
    return max(0.0, min(1.0, remaining / total))


def compute_confidence(listing: Listing) -> int:
    """0-100: how much to trust this listing's numbers (plan section 4, step 6).
    Blends value-source agreement, listing freshness, WFL vote volume, and
    whether the trade's Beli balance could even be verified.

    The Beli-verifiable factor exists because of a real pattern found in live
    data: trades involving "Limited"-rarity items (no in-game dealer price,
    community-submitted value only) can show wildly inflated, unverifiable
    value estimates — e.g. a common Mythical fruit "trading" for a Limited
    valued at billions. Those trades can't be checked against the real 40%
    Beli rule at all (see matcher.passes_beli_balance), so they get a hard
    confidence penalty here rather than being scored as if they were as
    trustworthy as an ordinary fruit-for-fruit trade."""
    involved = listing.give + listing.want
    agreement = _value_agreement(involved)
    freshness = _freshness(listing)

    total_votes = sum(listing.wfl.values())
    vote_confidence = min(1.0, total_votes / 5)  # 5+ votes = fully weighted

    give_beli = sum(i.beli_price for i in listing.want)
    get_beli = sum(i.beli_price for i in listing.give)
    beli_verifiable = 1.0 if (give_beli > 0 and get_beli > 0) else 0.0

    score = agreement * 0.30 + freshness * 0.20 + vote_confidence * 0.15 + beli_verifiable * 0.35
    return round(score * 100)


def compute_score(delta: int, profit_pct: float, demand: int, wfl: dict[str, int], confidence: int) -> float:
    """Ranking score: profit-dominant, then demand, then WFL win-lean, then confidence.
    Weights are tunable — this is a reasonable default, not a fixed law."""
    total_votes = sum(wfl.values())
    wfl_lean = (wfl.get("win", 0) - wfl.get("lose", 0)) / total_votes if total_votes > 0 else 0.0

    return (profit_pct * 1000) + (demand * 10) + (wfl_lean * 20) + (confidence * 0.5)
