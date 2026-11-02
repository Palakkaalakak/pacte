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
EDGE_KEEP = 3  # interchangeable listings kept per item-for-item swap
MAX_EXPANSIONS = 200_000  # safety cap on search work when steps are unlimited


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
    max_steps: int | None = 3,  # None = unlimited (every item is visited at most once, so it terminates)
    min_profit: int = 0,
    target_names: set[str] | None = None,
    now: datetime | None = None,
) -> list[Chain]:
    """All chains starting from an item in `inventory_counts`, best first.

    A chain is kept if it profits at least `min_profit` (end value - start
    value, > 0 when min_profit is 0) or ends on a name in `target_names`."""
    now = now or datetime.now(timezone.utc)
    targets = {n.lower() for n in (target_names or set())}

    # Edge table: wanted item -> {given item -> [freshest listings]}. A chain's profit depends
    # only on the ITEMS it passes through, so listings that make the same swap are
    # interchangeable: keep the freshest EDGE_KEEP of each swap instead of branching on
    # hundreds of duplicates (the main cost on a multi-site book).
    groups: dict[str, dict[tuple[str, int], list[tuple[float, Listing]]]] = defaultdict(lambda: defaultdict(list))
    display: dict[str, str] = {}
    start_value: dict[str, int] = {}
    for lst in listings:
        if len(lst.want) != 1 or len(lst.give) != 1:
            continue
        age = _age_minutes(lst, now)
        if age > max_age_minutes:
            continue
        w, g = lst.want[0], lst.give[0]
        wk, gk = w.name.lower(), g.name.lower()
        display.setdefault(wk, w.name)
        display.setdefault(gk, g.name)
        start_value.setdefault(wk, w.value(value_basis))
        # the end value is per listing (the same item can be priced differently by source)
        groups[wk][(gk, g.value(value_basis))].append((age, lst))
    # edges[want] = [(next item, value of it, freshest EDGE_KEEP listings)]
    edges: dict[str, list[tuple[str, int, list[tuple[float, Listing]]]]] = {}
    for wk, by_give in groups.items():
        out = []
        for (gk, val), lst_list in by_give.items():
            lst_list.sort(key=lambda x: x[0])
            out.append((gk, val, lst_list[:EDGE_KEEP]))
        edges[wk] = out

    results: list[Chain] = []
    expansions = [0]

    def dfs(start: str, start_value: int, path: list[tuple[float, Listing]], items: list[str], seen: set[str]) -> None:
        if len(results) >= MAX_CHAINS or expansions[0] > MAX_EXPANSIONS:
            return
        expansions[0] += 1
        for nxt, end_value, lst_list in edges.get(items[-1], ()):
            closes = nxt == start
            if not closes and nxt in seen:
                continue  # don't wander through an item twice
            profit = end_value - start_value
            keep = (profit >= min_profit if min_profit > 0 else profit > 0) or nxt in targets
            if closes and profit <= 0 and nxt not in targets:
                keep = False
            for age, lst in lst_list:
                if any(lst is p for _, p in path):
                    continue
                new_path = path + [(age, lst)]
                if keep:
                    results.append(Chain(
                        steps=[l for _, l in new_path], items=[display[i] for i in items + [nxt]],
                        start_value=start_value, end_value=end_value,
                        oldest_minutes=max(a for a, _ in new_path), is_cycle=closes,
                    ))
                    if len(results) >= MAX_CHAINS:
                        return
                if (max_steps is None or len(new_path) < max_steps) and not closes:
                    dfs(start, start_value, new_path, items + [nxt], seen | {nxt})

    for name, qty in inventory_counts.items():
        if qty <= 0 or name not in edges:
            continue
        dfs(name, start_value[name], [], [name], {name})

    results.sort(key=lambda c: (-c.profit, len(c.steps), c.oldest_minutes))
    return results
