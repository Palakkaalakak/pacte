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
    "bloxvalues": "BloxValues.net",
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
    adjusted: dict[str, float] = field(default_factory=dict)  # values put on Gamersberg's price level (per class)
    adjusted_platform: dict[str, float] = field(default_factory=dict)  # same, using ONE level per site for all classes

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
        """Effective gap: high minus low once every site is on Gamersberg's price level."""
        v = self._vals(True)
        return int(max(v.values()) - min(v.values()))

    @property
    def raw_gap(self) -> int:
        return max(self.values.values()) - min(self.values.values())


@dataclass
class ItemArb:
    """Buy item X in one listing, sell the SAME item X in another."""
    item: str
    buy: Listing      # gives X, wants `pay` items
    sell: Listing     # wants X, gives `receive` items
    cost: int         # value of what you pay for X (buy.want)
    revenue: int      # value of what you receive for X (sell.give)
    buy_norm: float = 1.0   # that site's typical (what a poster gives)/(what it asks), same units
    sell_norm: float = 1.0

    @property
    def vs_norm(self) -> float:
        """Round trip relative to what a typical buy-here/sell-there round trip returns. 1.00 means
        exactly the usual deal for those two sites; 1.30 means 30% better than their usual."""
        return (self.revenue / self.cost) / (self.buy_norm * self.sell_norm)

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


def site_norms(listings: list[Listing], value_basis: str = GB) -> dict[str, tuple[float, int]]:
    """source -> (median of value(poster gives)/value(poster asks), listings used).

    Posters ask for more than they give (the taker's premium), and how much differs by site.
    Uniform changes in a value table cancel out in barter, but this spread does not, so it is
    the honest yardstick for 'is this deal good for THIS site?'."""
    import statistics
    maps = value_maps(listings)
    per: dict[str, list[float]] = {}
    for lst in listings:
        give = sum(_value(i, value_basis, maps) for i in lst.give)
        want = sum(_value(i, value_basis, maps) for i in lst.want)
        if give > 0 and want > 0 and all(_value(i, value_basis, maps) > 0 for i in (*lst.give, *lst.want)):
            per.setdefault(lst.source, []).append(give / want)
    return {src: (statistics.median(r), len(r)) for src, r in per.items() if len(r) >= MIN_CLASS_ITEMS}


def platform_wide_inflation(listings: list[Listing]) -> dict[str, tuple[float, int]]:
    """site -> (median price ratio vs Gamersberg over EVERY item both price, count): one number per
    site, ignoring item class (compare platform_inflation, which is per class)."""
    import statistics
    ratios: dict[str, list[float]] = {}
    for _, _, vals in _item_table(listings).values():
        ref = vals.get(REFERENCE)
        if not ref:
            continue
        for k, v in vals.items():
            if k != REFERENCE:
                ratios.setdefault(k, []).append(v / ref)
    return {k: (statistics.median(r), len(r)) for k, r in ratios.items()}


def item_gaps(listings: list[Listing], *, min_ratio: float = 1.001, min_gap: int = 0,
              adjust_inflation: bool = True) -> list[ItemGap]:
    """Items two or more sites price differently. With `adjust_inflation` each site's value is
    first divided by that site's typical level for the item's class (see platform_inflation), so
    only a gap bigger than the site's usual markup counts."""
    infl = platform_inflation(listings) if adjust_inflation else {}
    wide = platform_wide_inflation(listings) if adjust_inflation else {}
    gaps = []
    for display, cls, values in _item_table(listings).values():
        if len(values) < 2:
            continue                       # need two sites' opinions to have a gap
        adjusted = {}
        for k, v in values.items():
            level, n = infl.get(cls, {}).get(k, (1.0, 0))
            adjusted[k] = v / level if (level and n >= MIN_CLASS_ITEMS) else float(v)
        adjusted_platform = {}
        for k, v in values.items():
            level, n = wide.get(k, (1.0, 0))
            adjusted_platform[k] = v / level if (level and n >= MIN_CLASS_ITEMS) else float(v)
        g = ItemGap(display, values, cls, adjusted, adjusted_platform)
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
    judge_by_norm: bool = False,
) -> list[ItemArb]:
    """Same-item arbitrage. For every item X: a listing that GIVES exactly one X
    (the buy) paired with a listing that WANTS exactly one X (the sell). You pay the
    buy listing's `want`, receive the sell listing's `give`; X passes straight through.
    Both legs are valued with ONE common basis so the profit is real, not a valuation
    artifact. `inventory_counts` restricts buys to ones you can pay for."""
    maps = value_maps(listings)
    norms = {src: n for src, (n, _) in site_norms(listings, value_basis).items()}
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
            if best_rev <= cost:
                break                                       # costs only rise from here: no real profit left
            if not judge_by_norm:
                if (best_rev - cost) / cost < min_pct:
                    break
                if len(top) >= per_item and (best_rev - cost) / cost <= top[0][0]:
                    break                                   # can't beat what we already hold
            for rev, sell in sell_list:
                if rev <= cost:
                    break                                   # sells only fall from here: no real profit
                if buy is sell or (cross_site_only and buy.source == sell.source):
                    continue
                bn, sn = norms.get(buy.source, 1.0), norms.get(sell.source, 1.0)
                # Real profit is always required; judge_by_norm additionally scores the deal
                # against the two sites' usual spread instead of against break-even.
                pct = ((rev / cost) / (bn * sn) - 1) if judge_by_norm else (rev - cost) / cost
                if pct < min_pct:
                    if judge_by_norm:
                        continue
                    break                                   # sells only fall from here
                if len(top) >= per_item and pct <= top[0][0]:
                    if judge_by_norm:
                        continue
                    break
                arb = ItemArb(buy.give[0].name, buy, sell, cost, rev, bn, sn)
                if len(top) < per_item:
                    heapq.heappush(top, (pct, id(arb), arb))
                else:
                    heapq.heapreplace(top, (pct, id(arb), arb))
        out.extend(a for _, _, a in top)
    out.sort(key=(lambda a: -a.vs_norm) if judge_by_norm else (lambda a: -a.profit_pct))
    return out


# ------------------------------------------------------------- gap exploits
# A value gap is only worth something if you can TRADE through it. Posters price items with
# their own site's numbers, so a site that undervalues item X (on the corrected platform-wide
# scale) has posters who give X away cheaply, and a site that overvalues X has posters who pay a
# lot for it. Every trade is judged on ONE fair scale: each site's number divided by that site's
# platform-wide price level (see platform_wide_inflation), then the median across sites. That
# strips both the site's general inflation and its quirks, so a profit here is not just
# "site A's numbers are bigger".

@dataclass
class GapExploit:
    kind: str                 # "buy" (get X cheap), "sell" (sell X dear) or "round" (buy + sell X)
    item: str
    edge: float               # X's corrected platform-wide gap: dearest site / cheapest site
    cheap_on: list[str]       # sites (display names) that price X below its fair value
    dear_on: list[str]        # sites that price X above its fair value
    legs: list[Listing]       # 1 listing, or [buy, sell] for a round trip
    pay: list[CatalogItem]    # what you hand over (for a round trip: the buy leg's ask)
    receive: list[CatalogItem]  # what you end up with (round trip: the sell leg's offer)
    cost: float               # fair value of `pay`
    revenue: float            # fair value of `receive`

    @property
    def profit(self) -> int:
        return round(self.revenue) - round(self.cost)   # matches the rounded cost/value shown

    @property
    def profit_pct(self) -> float:
        return (self.revenue - self.cost) / self.cost if self.cost else 0.0

    @property
    def oldest_minutes(self) -> float:
        now = datetime.now(timezone.utc)
        return max(
            (now - (l.created_at if l.created_at.tzinfo else l.created_at.replace(tzinfo=timezone.utc))).total_seconds() / 60
            for l in self.legs
        )


def platform_corrected_values(listings: list[Listing]) -> dict[str, dict[str, float]]:
    """item (lower) -> site -> that site's value divided by the site's platform-wide price level
    (Gamersberg's scale). Sites with too few shared items to measure a level are left as-is."""
    wide = platform_wide_inflation(listings)
    out: dict[str, dict[str, float]] = {}
    for lower, (_, _, vals) in _item_table(listings).items():
        row = {}
        for k, v in vals.items():
            level, n = wide.get(k, (1.0, 0))
            row[k] = v / level if (level and n >= MIN_CLASS_ITEMS) else float(v)
        if row:
            out[lower] = row
    return out


def fair_values(corrected: dict[str, dict[str, float]]) -> dict[str, float]:
    """item (lower) -> fair value: median of every site's corrected platform-wide value."""
    import statistics
    return {lower: statistics.median(row.values()) for lower, row in corrected.items() if row}


def find_gap_exploits(
    listings: list[Listing],
    *,
    min_edge: float = 1.10,
    min_pct: float = 0.05,
    max_age_minutes: float | None = None,
    inventory_counts: Counter[str] | None = None,
    per_item: int = 5,
    now: datetime | None = None,
) -> list[GapExploit]:
    """Trades that cash in on value gaps, valued on corrected platform-wide (fair) values.

      buy   - a listing on a site that UNDERprices gap item X gives X; you pay its ask.
      sell  - a listing on a site that OVERprices X wants X; you hand X over, take its offer.
      round - buy X on an underpricing site and sell that same X on an overpricing one; X only
              passes through your hands, so you only need what the buy leg asks for.

    Only items whose corrected platform-wide gap is >= `min_edge` count, and every trade must
    profit >= `min_pct` on fair values. `inventory_counts` keeps only trades you can pay for.
    Price levels are measured on the whole book; `max_age_minutes` only limits which listings
    can be traded."""
    corrected = platform_corrected_values(listings)       # full book: more data, steadier levels
    fair = fair_values(corrected)
    gaps: dict[str, tuple[float, set[str], set[str]]] = {}
    for lower, row in corrected.items():
        if len(row) < 2 or min(row.values()) <= 0:
            continue
        edge = max(row.values()) / min(row.values())
        if edge >= min_edge:
            f = fair[lower]
            gaps[lower] = (edge, {k for k, v in row.items() if v < f}, {k for k, v in row.items() if v > f})
    if not gaps:
        return []

    now = now or datetime.now(timezone.utc)
    if max_age_minutes:
        def _fresh(l: Listing) -> bool:
            c = l.created_at if l.created_at.tzinfo else l.created_at.replace(tzinfo=timezone.utc)
            return (now - c).total_seconds() <= max_age_minutes * 60
        listings = [l for l in listings if _fresh(l)]

    def fv(items: list[CatalogItem]) -> float | None:
        total = 0.0
        for i in items:
            v = fair.get(i.name.lower())
            if not v:
                return None                                # an unpriced item: can't judge the trade
            total += v
        return total

    def can_pay(items: list[CatalogItem]) -> bool:
        if inventory_counts is None:
            return True
        need = Counter(i.name.lower() for i in items)
        return all(inventory_counts.get(n, 0) >= q for n, q in need.items())

    def names(lower: set[str]) -> list[str]:
        return sorted(SITE_VALUE_KEYS.get(k, k) for k in lower)

    def make(kind: str, key: str, legs: list[Listing], pay, receive, cost: float, rev: float) -> GapExploit:
        edge, cheap, dear = gaps[key]
        display = next(i.name for l in legs for i in (*l.give, *l.want) if i.name.lower() == key)
        return GapExploit(kind, display, edge, names(cheap), names(dear), legs, list(pay), list(receive), cost, rev)

    singles: list[GapExploit] = []
    buys: dict[str, list[tuple[float, Listing]]] = {}
    sells: dict[str, list[tuple[float, Listing]]] = {}
    for lst in listings:
        if not lst.give or not lst.want:
            continue
        give_v, want_v = fv(lst.give), fv(lst.want)
        if not give_v or not want_v:
            continue
        src = lst.source
        # The gap item this poster misprices most: underpriced in what they give (you buy it
        # cheap), overpriced in what they want (you sell it dear).
        cheap_hits = [k for k in {i.name.lower() for i in lst.give} if k in gaps and src in gaps[k][1]]
        dear_hits = [k for k in {i.name.lower() for i in lst.want} if k in gaps and src in gaps[k][2]]
        payable = can_pay(lst.want)
        if (cheap_hits or dear_hits) and payable and (give_v - want_v) / want_v >= min_pct:
            if cheap_hits:
                key = max(cheap_hits, key=lambda k: gaps[k][0])
                singles.append(make("buy", key, [lst], lst.want, lst.give, want_v, give_v))
            else:
                key = max(dear_hits, key=lambda k: gaps[k][0])
                singles.append(make("sell", key, [lst], lst.want, lst.give, want_v, give_v))
        # Round-trip legs: exactly one X changes hands on each side.
        if len(lst.give) == 1 and cheap_hits and payable:
            buys.setdefault(cheap_hits[0], []).append((want_v, lst))
        if len(lst.want) == 1 and dear_hits:
            sells.setdefault(dear_hits[0], []).append((give_v, lst))

    rounds: list[GapExploit] = []
    for key, buy_list in buys.items():
        sell_list = sells.get(key)
        if not sell_list:
            continue
        buy_list.sort(key=lambda x: x[0])                     # cheapest ask first
        sell_list.sort(key=lambda x: x[0], reverse=True)      # richest offer first
        found: list[GapExploit] = []
        for cost, buy in buy_list:
            if (sell_list[0][0] - cost) / cost < min_pct:
                break                                         # asks only rise from here
            for rev, sell in sell_list:
                if (rev - cost) / cost < min_pct:
                    break                                     # offers only fall from here
                if buy is sell:
                    continue
                found.append(make("round", key, [buy, sell], buy.want, sell.give, cost, rev))
                break                                         # best sell for this buy
            if len(found) >= per_item:
                break
        rounds.extend(found)

    out = rounds + singles
    out.sort(key=lambda e: (-e.profit_pct, -e.profit))
    return out
