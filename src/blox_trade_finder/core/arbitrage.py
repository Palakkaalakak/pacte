"""Cross-site arbitrage: Gamersberg vs bloxfruitsvalues.com disagree on values.

Two views of the same discrepancy:
  * item_gaps       – items the two sites price differently (ratio + absolute gap).
  * find_gap_trades – live listings valued under BOTH sites' numbers. A trade that
                      profits under both is a consensus win; one that profits under
                      only one site's numbers is a valuation-gap trade (you receive
                      items the other site prices higher, so you can flip them there).

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
class GapTrade:
    listing: Listing
    give_gb: int
    get_gb: int
    give_bfv: int
    get_bfv: int

    @property
    def profit_gb(self) -> int:
        return self.get_gb - self.give_gb

    @property
    def profit_bfv(self) -> int:
        return self.get_bfv - self.give_bfv

    @property
    def pct_gb(self) -> float:
        return self.profit_gb / self.give_gb if self.give_gb else 0.0

    @property
    def pct_bfv(self) -> float:
        return self.profit_bfv / self.give_bfv if self.give_bfv else 0.0

    @property
    def consensus(self) -> bool:
        return self.profit_gb > 0 and self.profit_bfv > 0

    @property
    def best_pct(self) -> float:
        return max(self.pct_gb, self.pct_bfv)

    @property
    def edge_site(self) -> str:
        return "Gamersberg" if self.pct_gb >= self.pct_bfv else "bloxfruitsvalues"


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


def find_gap_trades(
    listings: list[Listing],
    *,
    min_pct: float = 0.10,
    require_consensus: bool = False,
    inventory_counts: Counter[str] | None = None,
) -> list[GapTrade]:
    """You give `listing.want`, you get `listing.give`. Both sites' numbers must
    exist for every item (otherwise we can't compare). Best (highest min-profit) first."""
    bfv_map = bfv_value_map(listings)
    out: list[GapTrade] = []
    for lst in listings:
        if not lst.give or not lst.want:
            continue
        if inventory_counts is not None:
            need = Counter(i.name.lower() for i in lst.want)
            if any(inventory_counts.get(n, 0) < q for n, q in need.items()):
                continue
        give_gb = sum(_gb_value(i) for i in lst.want)
        get_gb = sum(_gb_value(i) for i in lst.give)
        give_bfv = sum(_bfv_value(i, bfv_map) for i in lst.want)
        get_bfv = sum(_bfv_value(i, bfv_map) for i in lst.give)
        if min(give_gb, get_gb, give_bfv, get_bfv) <= 0 or any(
            _gb_value(i) <= 0 or _bfv_value(i, bfv_map) <= 0 for i in (*lst.give, *lst.want)
        ):
            continue
        t = GapTrade(lst, give_gb, get_gb, give_bfv, get_bfv)
        if t.best_pct < min_pct or (require_consensus and not t.consensus):
            continue
        out.append(t)
    out.sort(key=lambda t: (-(t.consensus), -min(t.pct_gb, t.pct_bfv), -t.best_pct))
    return out
