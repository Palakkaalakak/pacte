"""Cross-site arbitrage across every supported site.

Arbitrage is about the SAME item:
  * item_gaps           – items the sites price differently (Gamersberg, bloxfruitsvalues.com and
                          every extra site that publishes its own numbers).
  * find_item_arbitrage – buy item X in one listing, sell the SAME X in another for more
                          (priced on one common basis), ideally across sites.

Every listing item carries Gamersberg's catalog value plus, when its site publishes one, that
site's own number under the site id. `value_maps` harvests each site's prices seen anywhere in the
book, so a listing from site A can be re-valued with site B's numbers.
"""
from __future__ import annotations

import heapq
from collections import Counter
from datetime import datetime, timezone
from dataclasses import dataclass, field

from blox_trade_finder.models import CatalogItem, Listing

GB, BFV = "gamersberg", "bloxfruitsvalues"
# Value columns that belong to a scanned site, with display names.
SITE_VALUE_KEYS: dict[str, str] = {
    "gamersberg": "Gamersberg", "bloxfruitsvalues": "bloxfruitsvalues.com", "fantasyblox": "FantasyBlox",
    "tradehub": "Trade Hub", "tradebloxfruit": "TradeBloxFruit", "bfvgg": "BloxFruitsValues.gg",
}


def item_class(item: CatalogItem) -> str:
    """Coarse class used to compare like with like when judging site-wide price levels."""
    name = item.name.strip().lower()
    typ = (item.type or "").strip().lower()
    if name.startswith("permanent "):
        return "Permanent"
    if "skin" in typ or name.endswith(" skin"):
        return "Skins"
    if typ in ("", "0", "nan", "none") or "gamepass" in typ or "scroll" in name:
        return "Other (limiteds, gamepasses, scrolls...)"
    return "Physical fruits"


REFERENCE = GB          # every site's level is expressed relative to Gamersberg's
MIN_CLASS_ITEMS = 3     # fewer shared items than this => no reliable level, assume 1.0


@dataclass
class ItemGap:
    name: str
    values: dict[str, int] = field(default_factory=dict)   # site id -> that site's raw value (> 0)
    cls: str = ""
    adjusted: dict[str, float] = field(default_factory=dict)  # values put on Gamersberg's price level

    def _vals(self, adjusted: bool) -> dict:
        return self.adjusted if (adjusted and self.adjusted) else self.values

    @property
    def high_key(self) -> str:
        v = self._vals(True)
        return max(v, key=v.get)

    @property
    def low_key(self) -> str:
        v = self._vals(True)
        return min(v, key=v.get)

    @property
    def raw_ratio(self) -> float:
        return max(self.values.values()) / min(self.values.values())

    @property
    def ratio(self) -> float:
        """Gap after removing each site's general price level for this class."""
        v = self._vals(True)
        return max(v.values()) / min(v.values())

    @property
    def higher_on(self) -> str:
        return SITE_VALUE_KEYS.get(self.high_key, self.high_key)

    @property
    def lower_on(self) -> str:
        return SITE_VALUE_KEYS.get(self.low_key, self.low_key)

    @property
    def gap(self) -> int:
        v = self._vals(True)
        return int(max(v.values()) - min(v.values()))


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
    def oldest_minutes(self) -> float:
        now = datetime.now(timezone.utc)
        return max(
            (now - (l.created_at if l.created_at.tzinfo else l.created_at.replace(tzinfo=timezone.utc))).total_seconds() / 60
            for l in (self.buy, self.sell)
        )

    @property
    def cross_site(self) -> bool:
        return self.buy.source != self.sell.source


def value_maps(listings: list[Listing]) -> dict[str, dict[str, int]]:
    """site id -> {item name (lower): that site's value}, from every item in the book."""
    maps: dict[str, dict[str, int]] = {k: {} for k in SITE_VALUE_KEYS}
    for lst in listings:
        for item in (*lst.give, *lst.want):
            name = item.name.lower()
            for k, v in item.values.items():
                if k in maps and v > 0:
                    maps[k][name] = v
    return maps


def bfv_value_map(listings: list[Listing]) -> dict[str, int]:
    return value_maps(listings)[BFV]


def _value(item: CatalogItem, key: str, maps: dict[str, dict[str, int]]) -> int:
    return item.values.get(key, 0) or maps.get(key, {}).get(item.name.lower(), 0)


def _item_table(listings: list[Listing]) -> dict[str, tuple[str, dict[str, int]]]:
    maps = value_maps(listings)
    info: dict[str, tuple[str, str]] = {}
    for lst in listings:
        for item in (*lst.give, *lst.want):
            info.setdefault(item.name.lower(), (item.name, item_class(item)))
    return {
        lower: (disp, cls, {k: m[lower] for k, m in maps.items() if lower in m})
        for lower, (disp, cls) in info.items()
    }


def platform_inflation(listings: list[Listing]) -> dict[str, dict[str, tuple[float, int]]]:
    """class -> site -> (median price ratio vs Gamersberg over the items both price, how many).
    1.10 means that site prices this class ~10% higher than Gamersberg across the board, so a
    10% gap on one item there is just the site's normal level, not an opportunity."""
    import statistics
    ratios: dict[str, dict[str, list[float]]] = {}
    for _, cls, vals in _item_table(listings).values():
        ref = vals.get(REFERENCE)
        if not ref:
            continue
        for k, v in vals.items():
            if k != REFERENCE:
                ratios.setdefault(cls, {}).setdefault(k, []).append(v / ref)
    return {
        cls: {k: (statistics.median(r), len(r)) for k, r in by_site.items()}
        for cls, by_site in ratios.items()
    }


def item_gaps(listings: list[Listing], *, min_ratio: float = 1.25, min_gap: int = 0,
              adjust_inflation: bool = True) -> list[ItemGap]:
    """Items two or more sites price differently. With `adjust_inflation` each site's value is
    first divided by that site's typical level for the item's class (see platform_inflation), so
    only a gap bigger than the site's usual markup counts."""
    infl = platform_inflation(listings) if adjust_inflation else {}
    gaps = []
    for display, cls, values in _item_table(listings).values():
        if len(values) < 2:
            continue                       # need two sites' opinions to have a gap
        adjusted = {}
        for k, v in values.items():
            level, n = infl.get(cls, {}).get(k, (1.0, 0))
            adjusted[k] = v / level if (level and n >= MIN_CLASS_ITEMS) else float(v)
        g = ItemGap(display, values, cls, adjusted)
        if g.ratio >= min_ratio and g.gap >= min_gap:
            gaps.append(g)
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
    max_age_minutes: float | None = None,
    now: datetime | None = None,
) -> list[ItemArb]:
    """Same-item arbitrage. For every item X: a listing that GIVES exactly one X
    (the buy) paired with a listing that WANTS exactly one X (the sell). You pay the
    buy listing's `want`, receive the sell listing's `give`; X passes straight through.
    Both legs are valued with ONE common basis so the profit is real, not a valuation
    artifact. `inventory_counts` restricts buys to ones you can pay for."""
    maps = value_maps(listings)
    now = now or datetime.now(timezone.utc)
    if max_age_minutes:  # stale ads are probably filled or the poster is offline
        def _fresh(l: Listing) -> bool:
            c = l.created_at if l.created_at.tzinfo else l.created_at.replace(tzinfo=timezone.utc)
            return (now - c).total_seconds() <= max_age_minutes * 60
        listings = [l for l in listings if _fresh(l)]

    def val(items: list[CatalogItem]) -> int:
        return sum(_value(i, value_basis, maps) for i in items)

    # One pass over the book: value each listing ONCE, bucket buys/sells per item.
    buys: dict[str, list[tuple[int, Listing]]] = {}
    sells: dict[str, list[tuple[int, Listing]]] = {}
    for lst in listings:
        if not lst.give or not lst.want:
            continue
        if len(lst.give) == 1:
            if inventory_counts is not None:
                need = Counter(i.name.lower() for i in lst.want)
                if any(inventory_counts.get(n, 0) < q for n, q in need.items()):
                    continue
            cost = val(lst.want)
            if cost > 0:
                buys.setdefault(lst.give[0].name.lower(), []).append((cost, lst))
        if len(lst.want) == 1:
            rev = val(lst.give)
            if rev > 0:
                sells.setdefault(lst.want[0].name.lower(), []).append((rev, lst))

    out: list[ItemArb] = []
    for key, buy_list in buys.items():
        sell_list = sells.get(key)
        if not sell_list:
            continue
        buy_list.sort(key=lambda x: x[0])                   # cheapest buy first
        sell_list.sort(key=lambda x: x[0], reverse=True)    # richest sell first
        best_rev = sell_list[0][0]
        top: list[tuple[float, int, ItemArb]] = []          # min-heap of the best `per_item` pairs
        for cost, buy in buy_list:
            if best_rev <= cost or (best_rev - cost) / cost < min_pct:
                break                                       # costs only rise from here: no pair can qualify
            if len(top) >= per_item and (best_rev - cost) / cost <= top[0][0]:
                break                                       # can't beat what we already hold
            for rev, sell in sell_list:
                if rev <= cost or (rev - cost) / cost < min_pct:
                    break                                   # sells only fall from here
                if buy is sell or (cross_site_only and buy.source == sell.source):
                    continue
                pct = (rev - cost) / cost
                if len(top) >= per_item and pct <= top[0][0]:
                    break
                arb = ItemArb(buy.give[0].name, buy, sell, cost, rev)
                if len(top) < per_item:
                    heapq.heappush(top, (pct, id(arb), arb))
                else:
                    heapq.heapreplace(top, (pct, id(arb), arb))
        out.extend(a for _, _, a in top)
    out.sort(key=lambda a: -a.profit_pct)
    return out
