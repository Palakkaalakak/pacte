"""Cross-site arbitrage: Gamersberg vs bloxfruitsvalues.com disagree on values.

Arbitrage is about the SAME item:
  * item_gaps           – items the two sites price differently (ratio + absolute gap).
  * find_item_arbitrage – buy item X in one listing, sell X in another for more
                          (priced on one common basis), ideally across the two sites.

Gamersberg items carry only Gamersberg values; bloxfruitsvalues items carry their
own number (plus Gamersberg's when the name matches). `bfv_value_map` harvests every
bloxfruitsvalues price seen so Gamersberg-sourced listings can be re-valued too.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from blox_trade_finder.models import CatalogItem, Listing

GB, BFV = "gamersberg", "bloxfruitsvalues"


@dataclass
class ItemGap:
    name: str
    gb_value: int
    bfv_value: int

    @property
    def ratio(self) -> float:
        lo, hi = sorted((self.gb_value, self.bfv_value))
        return hi / lo if lo else float("inf")

    @property
    def higher_on(self) -> str:
        return "Gamersberg" if self.gb_value > self.bfv_value else "bloxfruitsvalues"

    @property
    def gap(self) -> int:
        return abs(self.gb_value - self.bfv_value)


@dataclass
class ItemArb:
    """Buy item X in one listing, sell the SAME item X in another."""
    item: str
    buy: Listing      # gives X, wants `pay` items
    sell: Listing     # wants X, gives `receive` items
    cost: int         # value of what you pay for X (buy.want)
    revenue: int      # value of what you receive for X (sell.give)

    @property
    def profit(self) -> int:
        return self.revenue - self.cost

    @property
    def profit_pct(self) -> float:
        return self.profit / self.cost if self.cost else 0.0

    @property
    def cross_site(self) -> bool:
        return self.buy.source != self.sell.source


def bfv_value_map(listings: list[Listing]) -> dict[str, int]:
    out: dict[str, int] = {}
    for lst in listings:
        for item in (*lst.give, *lst.want):
            v = item.values.get(BFV, 0)
            if v > 0:
                out[item.name.lower()] = v
    return out


def _gb_value(item: CatalogItem) -> int:
    return item.values.get(GB, 0)


def _bfv_value(item: CatalogItem, bfv_map: dict[str, int]) -> int:
    return item.values.get(BFV, 0) or bfv_map.get(item.name.lower(), 0)


def item_gaps(listings: list[Listing], *, min_ratio: float = 1.25, min_gap: int = 0) -> list[ItemGap]:
    bfv_map = bfv_value_map(listings)
    seen: dict[str, ItemGap] = {}
    for lst in listings:
        for item in (*lst.give, *lst.want):
            key = item.name.lower()
            if key in seen:
                continue
            gb, bfv = _gb_value(item), _bfv_value(item, bfv_map)
            if gb > 0 and bfv > 0:
                seen[key] = ItemGap(item.name, gb, bfv)
    gaps = [g for g in seen.values() if g.ratio >= min_ratio and g.gap >= min_gap]
    gaps.sort(key=lambda g: (-g.gap, -g.ratio))
    return gaps


def find_item_arbitrage(
    listings: list[Listing],
    *,
    value_basis: str = GB,
    min_pct: float = 0.10,
    cross_site_only: bool = True,
    inventory_counts: Counter[str] | None = None,
    per_item: int = 5,
) -> list[ItemArb]:
    """Same-item arbitrage. For every item X: a listing that GIVES exactly one X
    (the buy) paired with a listing that WANTS exactly one X (the sell). You pay the
    buy listing's `want`, receive the sell listing's `give`; X passes straight through.
    Both legs are valued with ONE common basis so the profit is real, not a valuation
    artifact. `inventory_counts` restricts buys to ones you can pay for."""
    bfv_map = bfv_value_map(listings)

    def val(items: list[CatalogItem]) -> int:
        if value_basis == BFV:
            return sum(_bfv_value(i, bfv_map) for i in items)
        return sum(i.values.get(value_basis, 0) for i in items)

    buys: dict[str, list[Listing]] = {}
    sells: dict[str, list[Listing]] = {}
    for lst in listings:
        if not lst.give or not lst.want:
            continue
        if len(lst.give) == 1:
            buys.setdefault(lst.give[0].name.lower(), []).append(lst)
        if len(lst.want) == 1:
            sells.setdefault(lst.want[0].name.lower(), []).append(lst)

    out: list[ItemArb] = []
    for key, buy_list in buys.items():
        for sell in sells.get(key, []):
            revenue = val(sell.give)
            if revenue <= 0:
                continue
            for buy in buy_list:
                if buy is sell or (cross_site_only and buy.source == sell.source):
                    continue
                if inventory_counts is not None:
                    need = Counter(i.name.lower() for i in buy.want)
                    if any(inventory_counts.get(n, 0) < q for n, q in need.items()):
                        continue
                cost = val(buy.want)
                if cost <= 0:
                    continue
                arb = ItemArb(buy.give[0].name, buy, sell, cost, revenue)
                if arb.profit > 0 and arb.profit_pct >= min_pct:
                    out.append(arb)
    out.sort(key=lambda a: -a.profit_pct)
    counts: Counter[str] = Counter()
    capped = []
    for a in out:  # keep the best few per item so one popular item doesn't flood the table
        if counts[a.item] < per_item:
            counts[a.item] += 1
            capped.append(a)
    return capped
