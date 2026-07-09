from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from blox_trade_finder.core.scoring import compute_confidence, compute_score, compute_values, compute_verdict
from blox_trade_finder.models import Goals, Listing, Match

logger = logging.getLogger(__name__)


def is_feasible(listing: Listing, inventory_counts: Counter[str]) -> bool:
    """Can you actually make this trade? Every item the poster wants must be
    in your inventory, respecting quantity (plan section 4, step 2)."""
    needed: Counter[str] = Counter()
    for item in listing.want:
        needed[item.name.lower()] += 1
    for name, qty in needed.items():
        if inventory_counts.get(name, 0) < qty:
            return False
    return True


BELI_MAX_IMBALANCE = 0.40  # Blox Fruits blocks trades where the sides differ by more than this


def passes_beli_balance(listing: Listing) -> bool:
    """Blox Fruits' own trade UI refuses to let a trade go through if the two
    sides' total in-game dealer Beli value differ by more than 40% — this is
    a hard game-engine rule, not a preference, so it can't be turned off via
    goals (not even goals.any). Uses `beli_price` (the real in-game stock
    price), never a trade site's gamersberg/fruityblox/etc. value estimate.

    If neither side has any Beli-priced item (e.g. trading only Permanent
    fruit variants or accessories, which aren't dealer-priced), there's
    nothing to evaluate, so this doesn't block — the restriction is understood
    to apply to Beli-priced (Physical) fruits specifically."""
    give_beli = sum(i.beli_price for i in listing.want)
    get_beli = sum(i.beli_price for i in listing.give)
    if give_beli <= 0 or get_beli <= 0:
        return True
    larger, smaller = max(give_beli, get_beli), min(give_beli, get_beli)
    return (larger - smaller) <= BELI_MAX_IMBALANCE * larger


def _listing_age_hours(listing: Listing) -> float:
    created = listing.created_at
    if not isinstance(created, datetime):
        created = datetime.fromisoformat(str(created))
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600


def _exceeds_qty_cap(listing: Listing, inventory_counts: Counter[str], max_qty_per_fruit: int) -> bool:
    """True if accepting this trade would leave you owning more than
    `max_qty_per_fruit` copies of any single fruit it gives you — checked
    per fruit name independently (a cap of 3 means up to 3 of EACH fruit,
    not a shared budget of 3 total)."""
    received: Counter[str] = Counter()
    for item in listing.give:
        received[item.name.lower()] += 1
    for name, qty_received in received.items():
        if inventory_counts.get(name, 0) + qty_received > max_qty_per_fruit:
            return True
    return False


def _passes_goals(
    listing: Listing, give_value: int, get_value: int, delta: int, profit_pct: float, demand: int,
    confidence: int, inventory_counts: Counter[str], goals: Goals,
) -> tuple[bool, str | None, list[str]]:
    """Returns (passed, rejected_by, reasons). `rejected_by` names the first
    filter that failed (for debug logging); None when it passed."""
    reasons: list[str] = []

    if goals.min_profit is not None and delta < goals.min_profit:
        return False, "min_profit", reasons
    if goals.min_profit_pct is not None and profit_pct < goals.min_profit_pct:
        return False, "min_profit_pct", reasons
    if goals.min_demand is not None and demand < goals.min_demand:
        return False, "min_demand", reasons
    if goals.want_item is not None:
        wanted = [goals.want_item] if isinstance(goals.want_item, str) else goals.want_item
        wanted_lower = {w.lower() for w in wanted}
        if goals.want_item_include_permanent:
            # Wanting "Kitsune" usually also means "or the Permanent version is
            # fine too" — add "Permanent X" for each name that isn't already
            # phrased that way.
            wanted_lower |= {
                f"permanent {w}" for w in wanted_lower if not w.startswith("permanent ")
            }
        give_names_lower = {i.name.lower() for i in listing.give}
        matched = wanted_lower & give_names_lower
        if not matched:
            return False, "want_item", reasons
        reasons.append(f"includes wanted item(s): {', '.join(sorted(matched))}")
    if goals.min_get_value is not None and get_value < goals.min_get_value:
        return False, "min_get_value", reasons
    if goals.max_give_value is not None and give_value > goals.max_give_value:
        return False, "max_give_value", reasons
    if goals.any_fair and delta < 0:
        return False, "any_fair", reasons
    if goals.exclude_lose_wfl and listing.wfl.get("lose", 0) > listing.wfl.get("win", 0) + listing.wfl.get("fair", 0):
        return False, "exclude_lose_wfl", reasons
    if goals.min_confidence is not None and confidence < goals.min_confidence:
        return False, "min_confidence", reasons
    if goals.max_age_hours is not None and _listing_age_hours(listing) > goals.max_age_hours:
        return False, "max_age_hours", reasons
    if goals.max_qty_per_fruit is not None and _exceeds_qty_cap(listing, inventory_counts, goals.max_qty_per_fruit):
        return False, "max_qty_per_fruit", reasons

    if delta > 0:
        reasons.append(f"+{delta:,} value ({profit_pct:+.0%})")
    return True, None, reasons


def find_matches(listings: list[Listing], inventory_counts: Counter[str], goals: Goals) -> list[Match]:
    logger.info(
        "matcher: evaluating %d listings (goals.any=%s, value_basis=%s)",
        len(listings), goals.any, goals.value_basis,
    )
    matches: list[Match] = []
    infeasible_count = 0
    beli_blocked_count = 0
    rejections: Counter[str] = Counter()

    for listing in listings:
        if not is_feasible(listing, inventory_counts):
            infeasible_count += 1
            logger.debug(
                "listing %s [%s]: infeasible — wants %s, inventory can't cover it",
                listing.id, listing.source, [i.name for i in listing.want],
            )
            continue

        if not passes_beli_balance(listing):
            beli_blocked_count += 1
            give_beli = sum(i.beli_price for i in listing.want)
            get_beli = sum(i.beli_price for i in listing.give)
            logger.debug(
                "listing %s [%s]: blocked by Blox Fruits' 40%% Beli-balance rule "
                "(give=%d beli, get=%d beli — game would refuse this trade)",
                listing.id, listing.source, give_beli, get_beli,
            )
            continue

        give_value, get_value, delta, profit_pct, demand = compute_values(listing, goals.value_basis)
        confidence = compute_confidence(listing)

        if goals.any:
            # goals.any=true: feasibility alone is enough, skip every other filter
            ok, rejected_by, reasons = True, None, []
        else:
            ok, rejected_by, reasons = _passes_goals(
                listing, give_value, get_value, delta, profit_pct, demand, confidence, inventory_counts, goals
            )

        if not ok:
            rejections[rejected_by or "unknown"] += 1
            logger.debug(
                "listing %s [%s]: rejected by goal '%s' (delta=%d, profit=%.0f%%, demand=%d, confidence=%d)",
                listing.id, listing.source, rejected_by, delta, profit_pct * 100, demand, confidence,
            )
            continue

        score = compute_score(delta, profit_pct, demand, listing.wfl, confidence)
        verdict = compute_verdict(listing)
        logger.debug(
            "listing %s [%s]: MATCH (delta=%d, profit=%.0f%%, demand=%d, confidence=%d, score=%.1f, verdict=%s)",
            listing.id, listing.source, delta, profit_pct * 100, demand, confidence, score, verdict,
        )

        matches.append(
            Match(
                listing=listing,
                give_value=give_value,
                get_value=get_value,
                delta=delta,
                profit_pct=profit_pct,
                demand=demand,
                confidence=confidence,
                score=score,
                reasons=reasons,
                verdict=verdict,
            )
        )

    # Ranked by absolute value delta (highest profit first), not the composite
    # score or profit percentage — a 10M-delta trade outranks a 90%-profit
    # trade on a 1M item. `score` is still computed and stored on Match in
    # case a different sort order is wanted later.
    matches.sort(key=lambda m: m.delta, reverse=True)
    result = matches[: goals.limit]
    logger.info(
        "matcher: %d listings -> %d infeasible, %d blocked by 40%% Beli rule, "
        "%d rejected by goals (%s), %d passed -> returning %d (limit=%d)",
        len(listings), infeasible_count, beli_blocked_count, sum(rejections.values()),
        dict(rejections), len(matches), len(result), goals.limit,
    )
    return result
