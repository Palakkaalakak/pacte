"""Chain trades: A -> B -> C ... where each listing wants what the previous gave.

The user holds item A. Listing 1 wants A and gives B; listing 2 wants B and
gives C; and so on. When the chain returns to a held item (a cycle, e.g. X wants
Y, Y wants Z, Z wants X) or ends on an item worth more than the start, the whole
chain can be run back to back for profit or to reach a wanted item.

Only 1-for-1 listings are chained (one item wanted, one item given) so every
hop is unambiguous. Every listing in the chain must be at most `max_age_minutes`
old, since stale ads usually mean the trade is gone.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from blox_trade_finder.models import Listing, ValueBasis

MAX_CHAINS = 500


@dataclass
class Chain:
    steps: list[Listing]       # in the order you execute them
    items: list[str]           # A, B, C, ... (len(steps) + 1 names)
    start_value: int
    end_value: int
    oldest_minutes: float
    is_cycle: bool             # ends back on an item you started with

    @property
    def profit(self) -> int:
        return self.end_value - self.start_value

    @property
    def profit_pct(self) -> float:
        return self.profit / self.start_value if self.start_value else 0.0


def _age_minutes(listing: Listing, now: datetime) -> float:
    created = listing.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created).total_seconds() / 60)


def find_chains(
    listings: list[Listing],
    inventory_counts: Counter[str],
    *,
    value_basis: ValueBasis = "gamersberg",
    max_age_minutes: float = 5,
    max_steps: int = 3,
    min_profit: int = 0,
    target_names: set[str] | None = None,
    now: datetime | None = None,
) -> list[Chain]:
    """All chains starting from an item in `inventory_counts`, best first.

    A chain is kept if it profits at least `min_profit` (end value - start
    value, > 0 when min_profit is 0) or ends on a name in `target_names`."""
    now = now or datetime.now(timezone.utc)
    targets = {n.lower() for n in (target_names or set())}

    by_want: dict[str, list[Listing]] = defaultdict(list)
    ages: dict[str, float] = {}
    for lst in listings:
        if len(lst.want) != 1 or len(lst.give) != 1:
            continue
        age = _age_minutes(lst, now)
        if age > max_age_minutes:
            continue
        ages[lst.id + lst.source] = age
        by_want[lst.want[0].name.lower()].append(lst)

    results: list[Chain] = []

    def value(l: Listing, side: str) -> int:
        item = (l.give if side == "give" else l.want)[0]
        return item.value(value_basis)

    def dfs(start_name: str, start_value: int, path: list[Listing], items: list[str]) -> None:
        if len(results) >= MAX_CHAINS:
            return
        current = items[-1]
        for lst in by_want.get(current.lower(), []):
            if any(lst is p for p in path):
                continue
            nxt = lst.give[0].name
            closes = nxt.lower() == start_name.lower()
            if not closes and nxt.lower() in {i.lower() for i in items}:
                continue  # don't wander through an item twice
            new_path = path + [lst]
            new_items = items + [nxt]
            end_value = lst.give[0].value(value_basis)
            profit = end_value - start_value
            keep = (profit >= min_profit if min_profit > 0 else profit > 0) or nxt.lower() in targets
            if keep and not (closes and profit <= 0 and nxt.lower() not in targets):
                results.append(Chain(
                    steps=new_path,
                    items=new_items,
                    start_value=start_value,
                    end_value=end_value,
                    oldest_minutes=max(ages[s.id + s.source] for s in new_path),
                    is_cycle=closes,
                ))
            if len(new_path) < max_steps and not closes:
                dfs(start_name, start_value, new_path, new_items)

    for name, qty in inventory_counts.items():
        if qty <= 0 or name not in by_want:
            continue
        sample = by_want[name][0].want[0]
        dfs(sample.name, sample.value(value_basis), [], [sample.name])

    results.sort(key=lambda c: (-c.profit, len(c.steps), c.oldest_minutes))
    return results
