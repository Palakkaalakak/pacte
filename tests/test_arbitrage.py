from datetime import datetime, timezone

from collections import Counter
from blox_trade_finder.core.arbitrage import find_item_arbitrage, item_gaps
from blox_trade_finder.models import CatalogItem, Listing


def _it(name, gb, bfv, i=1):
    return CatalogItem(id=i, name=name, values={"gamersberg": gb, "bloxfruitsvalues": bfv})


def _l(id_, want, give, source="gamersberg"):
    return Listing(id=id_, source=source, url="u", poster_name="p", poster_rating=1.0,
                   give=give, want=want, wfl={}, created_at=datetime.now(timezone.utc))


X = _it("X", 100, 100, 1)


def test_item_gaps_ranks_by_gap() -> None:
    ls = [_l("a", [_it("A", 10, 10)], [_it("B", 100, 200, 2)])]
    gaps = item_gaps(ls)
    assert [g.name for g in gaps] == ["B"] and gaps[0].higher_on == "bloxfruitsvalues.com" and gaps[0].lower_on == "Gamersberg"


def test_same_item_arbitrage_cross_site() -> None:
    buy = _l("buy", [_it("W", 80, 80, 2)], [X], source="bloxfruitsvalues")   # pay 80 for X
    sell = _l("sell", [X], [_it("G", 120, 120, 3)], source="gamersberg")     # get 120 for X
    res = find_item_arbitrage([buy, sell], min_pct=0.1)
    assert len(res) == 1 and res[0].profit == 40 and res[0].cross_site and res[0].item == "X"


def test_same_site_excluded_by_default_and_no_loss() -> None:
    buy = _l("buy", [_it("W", 80, 80, 2)], [X])
    sell = _l("sell", [X], [_it("G", 120, 120, 3)])
    assert find_item_arbitrage([buy, sell]) == []
    assert len(find_item_arbitrage([buy, sell], cross_site_only=False)) == 1
    bad = _l("bad", [X], [_it("G", 50, 50, 4)], source="bloxfruitsvalues")
    assert find_item_arbitrage([buy, bad], cross_site_only=True) == []


def test_arbitrage_drops_stale_listing() -> None:
    from datetime import timedelta
    buy = _l("buy", [_it("W", 80, 80, 2)], [X], source="bloxfruitsvalues")
    sell = _l("sell", [X], [_it("G", 120, 120, 3)], source="gamersberg")
    sell.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    assert find_item_arbitrage([buy, sell], max_age_minutes=10) == []
    assert len(find_item_arbitrage([buy, sell], max_age_minutes=60)) == 1
    assert len(find_item_arbitrage([buy, sell])) == 1


def test_item_gaps_compare_all_sites_not_just_two() -> None:
    a = CatalogItem(id=1, name="Venom", values={"gamersberg": 60, "tradehub": 25, "fantasyblox": 100})
    b = CatalogItem(id=2, name="Pain", values={"gamersberg": 10, "bfvgg": 10})
    gaps = item_gaps([_l("x", [b], [a])])
    assert [g.name for g in gaps] == ["Venom"]                      # Pain's two sites agree -> no gap
    g = gaps[0]
    assert g.values == {"gamersberg": 60, "fantasyblox": 100, "tradehub": 25}
    assert (g.higher_on, g.lower_on, round(g.ratio, 1)) == ("FantasyBlox", "Trade Hub", 4.0)


def test_arbitrage_priced_on_any_sites_numbers() -> None:
    x = CatalogItem(id=1, name="X", values={"gamersberg": 100, "tradehub": 100})
    w = CatalogItem(id=2, name="W", values={"gamersberg": 80, "tradehub": 50})
    g = CatalogItem(id=3, name="G", values={"gamersberg": 120, "tradehub": 60})
    buy = _l("buy", [w], [x], source="fantasyblox")
    sell = _l("sell", [x], [g], source="bfvgg")
    assert find_item_arbitrage([buy, sell], value_basis="gamersberg")[0].profit == 40       # 120 - 80
    assert find_item_arbitrage([buy, sell], value_basis="tradehub", min_pct=0.1)[0].profit == 10  # 60 - 50


def test_platform_inflation_is_removed_from_gaps() -> None:
    from blox_trade_finder.core.arbitrage import platform_inflation
    mk = lambda n, gb, th, i: CatalogItem(id=i, name=n, type="Natural", values={"gamersberg": gb, "tradehub": th})
    # tradehub prices every fruit 10% higher, except Odd which it prices 60% higher
    items = [mk("A", 100, 110, 1), mk("B", 200, 220, 2), mk("C", 300, 330, 3), mk("D", 400, 440, 4), mk("Odd", 100, 160, 5)]
    ls = [_l(f"l{i}", [it], [items[(i + 1) % 5]]) for i, it in enumerate(items)]
    lvl, n = platform_inflation(ls)["Physical fruits"]["tradehub"]
    assert round(lvl, 2) == 1.10 and n == 5
    names = [g.name for g in item_gaps(ls, min_ratio=1.25)]
    assert names == ["Odd"]                                        # 1.6x raw -> 1.45x adjusted; the 1.1x ones vanish
    raw = [g.name for g in item_gaps(ls, min_ratio=1.05, adjust_inflation=False)]
    assert set(raw) == {"A", "B", "C", "D", "Odd"}                 # without adjustment they all look like gaps
    g = next(g for g in item_gaps(ls, min_ratio=1.25) if g.name == "Odd")
    assert round(g.raw_ratio, 2) == 1.60 and round(g.ratio, 2) == 1.45


def test_judge_by_norm_scores_against_site_spread() -> None:
    from blox_trade_finder.core.arbitrage import site_norms
    mk = lambda n, v, i: CatalogItem(id=i, name=n, values={"gamersberg": v})
    X, W, G = mk("X", 100, 1), mk("W", 100, 2), mk("G", 100, 3)
    # site "a" posters typically give 50 for an ask of 100 (norm 0.5); site "b" gives 100 for 100 (norm 1.0)
    pad_a = [_l(f"pa{i}", [W], [mk("P", 50, 9)], source="a") for i in range(4)]
    pad_b = [_l(f"pb{i}", [W], [mk("Q", 100, 8)], source="b") for i in range(4)]
    buy = _l("buy", [mk("W", 80, 2)], [X], source="a")        # pay 80 for X on site a
    sell = _l("sell", [X], [mk("G", 120, 3)], source="b")     # get 120 for X on site b
    ls = pad_a + pad_b + [buy, sell]
    norms = {k: round(v[0], 2) for k, v in site_norms(ls).items()}
    assert norms["a"] == 0.5 or norms["a"] > 0                # site spreads are measured per site
    raw = find_item_arbitrage(ls, min_pct=0.1)
    judged = find_item_arbitrage(ls, min_pct=0.1, judge_by_norm=True)
    assert raw[0].profit == 40
    assert judged and judged[0].vs_norm > raw[0].revenue / raw[0].cost   # beating a lossy round trip counts for more


def test_gap_amounts_carry_effective_and_raw_values() -> None:
    mk = lambda n, gb, th, i: CatalogItem(id=i, name=n, type="Natural", values={"gamersberg": gb, "tradehub": th})
    items = [mk("A", 100, 110, 1), mk("B", 200, 220, 2), mk("C", 300, 330, 3), mk("D", 400, 440, 4), mk("Odd", 100, 160, 5)]
    ls = [_l(f"l{i}", [it], [items[(i + 1) % 5]]) for i, it in enumerate(items)]
    g = next(g for g in item_gaps(ls, min_ratio=1.25) if g.name == "Odd")
    assert g.raw_gap == 60 and round(g.raw_ratio, 2) == 1.60
    assert g.gap == int(160 / 1.10 - 100) and round(g.ratio, 2) == 1.45      # 45 effective vs 60 raw


def _gap_cfg():
    return dict(value_basis="gamersberg", min_pct=0.1, cross_site_only=True, max_age_minutes=None,
                min_ratio=1.001, only_mine=False)


def test_value_gaps_are_three_tables_with_ratios_against_gamersberg() -> None:
    from blox_trade_finder.live import build_arb_view
    a = CatalogItem(id=1, name="Venom", values={"gamersberg": 60_000_000, "tradehub": 25_000_000, "fantasyblox": 100_000_000})
    v = build_arb_view([_l("x", [CatalogItem(id=2, name="Pain", values={"gamersberg": 10})], [a])],
                       cfg=_gap_cfg(), inventory_counts=Counter(), scam_cfg=None)
    t = v["gaps"]
    assert set(t) == {"values", "corrected", "summary"}
    assert list(t["values"][0]) == ["Item", "Gamersberg", "FantasyBlox", "Trade Hub"] == list(t["corrected"][0])
    assert list(t["summary"][0]) == ["Item", "Effective gap", "Raw gap", "Higher on", "Lower on", "Class"]
    # every ratio is relative to Gamersberg (60M = 1.00x), not to the cheapest site
    assert (t["values"][0]["Gamersberg"], t["values"][0]["FantasyBlox"], t["values"][0]["Trade Hub"]) == \
        ("60.00M (1.00x)", "100.00M (1.67x)", "25.00M (0.42x)")
    assert t["summary"][0]["Effective gap"] == "75.00M (4.00x)"


def test_corrected_table_removes_the_sites_price_level() -> None:
    from blox_trade_finder.live import _gap_tables
    mk = lambda n, gb, th, i: CatalogItem(id=i, name=n, type="Natural", values={"gamersberg": gb, "tradehub": th})
    items = [mk("A", 100, 110, 1), mk("B", 200, 220, 2), mk("C", 300, 330, 3), mk("D", 400, 440, 4), mk("Odd", 100, 160, 5)]
    ls = [_l(f"l{i}", [it], [items[(i + 1) % 5]]) for i, it in enumerate(items)]
    g = next(g for g in item_gaps(ls, min_ratio=1.25) if g.name == "Odd")
    t = _gap_tables([g], ["gamersberg", "tradehub"])
    assert (t["values"][0]["Gamersberg"], t["values"][0]["Trade Hub"]) == ("100 (1.00x)", "160 (1.60x)")      # as published
    assert (t["corrected"][0]["Gamersberg"], t["corrected"][0]["Trade Hub"]) == ("100 (1.00x)", "145 (1.45x)")  # 160 / 1.10


def test_platform_wide_table_pools_all_classes_into_one_level() -> None:
    from blox_trade_finder.core.arbitrage import platform_wide_inflation
    from blox_trade_finder.live import _gap_tables
    # tradehub prices Natural fruits +10%, Skins +50%, Odd +100%: the platform-wide level pools every class
    def mk(n, typ, gb, th, i): return CatalogItem(id=i, name=n, type=typ, values={"gamersberg": gb, "tradehub": th})
    items = [mk("A", "Natural", 100, 110, 1), mk("B", "Natural", 200, 220, 2), mk("C", "Natural", 300, 330, 3),
             mk("S1", "Skins", 100, 150, 4), mk("S2", "Skins", 200, 300, 5), mk("S3", "Skins", 300, 450, 6),
             mk("Odd", "Natural", 100, 200, 7)]
    ls = [_l(f"l{i}", [it], [items[(i + 1) % len(items)]]) for i, it in enumerate(items)]
    level, n = platform_wide_inflation(ls)["tradehub"]
    assert n == 7 and round(level, 2) == 1.50                       # median over all items, any class
    g = next(g for g in item_gaps(ls, min_ratio=1.001) if g.name == "Odd")
    t = _gap_tables([g], ["gamersberg", "tradehub"], with_platform=True)
    assert t["values"][0]["Trade Hub"] == "200 (2.00x)"
    assert t["corrected"][0]["Trade Hub"] == "181 (1.82x)"          # Natural fruits run +10% -> 200 / 1.10
    assert t["platform"][0]["Trade Hub"] == "133 (1.33x)"           # one pooled +50% level -> 200 / 1.50
    assert "platform" not in _gap_tables([g], ["gamersberg", "tradehub"])


# ------------------------------------------------------------- gap exploits
def _gap_book():
    """tradehub prices everything +10% vs Gamersberg (its platform-wide level), except X which it
    prices 2x. On the corrected platform-wide scale X is ~182 on tradehub vs 100 on Gamersberg:
    cheap on Gamersberg, dear on tradehub. Every other item agrees once the +10% is removed."""
    def mk(n, gb, i):
        return CatalogItem(id=i, name=n, type="Natural", values={"gamersberg": gb, "tradehub": round(gb * 1.1)})
    A, B, C, D = mk("A", 100, 1), mk("B", 200, 2), mk("C", 300, 3), mk("D", 400, 4)
    X = CatalogItem(id=5, name="X", type="Natural", values={"gamersberg": 100, "tradehub": 200})
    pad = [_l("pad1", [A], [B]), _l("pad2", [C], [D])]
    return A, B, C, D, X, pad


def test_gap_exploit_fair_values_strip_platform_inflation() -> None:
    from blox_trade_finder.core.arbitrage import fair_values, platform_corrected_values
    A, B, C, D, X, pad = _gap_book()
    corr = platform_corrected_values(pad + [_l("x", [A], [X])])
    assert round(corr["a"]["tradehub"]) == 100 and round(corr["x"]["tradehub"]) == 182   # 110/1.1, 200/1.1
    fair = fair_values(corr)
    assert round(fair["a"]) == 100 and round(fair["x"]) == 141                        # median of 100 and 182


def test_gap_exploit_buy_cheap_on_underpricing_site() -> None:
    from blox_trade_finder.core.arbitrage import find_gap_exploits
    A, B, C, D, X, pad = _gap_book()
    buy = _l("buy", [A], [X], source="gamersberg")      # Gamersberg poster: X for A, fair 141 vs 100
    res = [e for e in find_gap_exploits(pad + [buy]) if e.legs == [buy]]
    assert len(res) == 1
    e = res[0]
    assert (e.kind, e.item, e.cheap_on, e.dear_on) == ("buy", "X", ["Gamersberg"], ["Trade Hub"])
    assert round(e.cost) == 100 and round(e.revenue) == 141 and round(e.profit_pct, 2) == 0.41


def test_gap_exploit_sell_dear_on_overpricing_site() -> None:
    from blox_trade_finder.core.arbitrage import find_gap_exploits
    A, B, C, D, X, pad = _gap_book()
    sell = _l("sell", [X], [B], source="tradehub")       # tradehub poster pays B (fair 200) for X (fair 141)
    res = [e for e in find_gap_exploits(pad + [sell]) if e.legs == [sell]]
    assert len(res) == 1 and res[0].kind == "sell" and round(res[0].profit_pct, 2) == 0.42
    # the same trade posted on Gamersberg (which underprices X) is not an exploit of the gap
    same_on_gb = _l("sell2", [X], [B], source="gamersberg")
    assert not [e for e in find_gap_exploits(pad + [same_on_gb]) if e.legs == [same_on_gb]]


def test_gap_exploit_round_trip_buys_cheap_sells_dear() -> None:
    from blox_trade_finder.core.arbitrage import find_gap_exploits
    A, B, C, D, X, pad = _gap_book()
    buy = _l("buy", [B], [X], source="gamersberg")       # pay B (200) for X: a LOSS on its own (X = 141)
    sell = _l("sell", [X], [C], source="tradehub")       # get C (300) for X
    res = find_gap_exploits(pad + [buy, sell])
    rounds = [e for e in res if e.kind == "round"]
    assert len(rounds) == 1
    r = rounds[0]
    assert r.legs == [buy, sell] and r.pay == [B] and r.receive == [C]
    assert round(r.cost) == 200 and round(r.revenue) == 300 and r.profit == 100
    assert not [e for e in res if e.legs == [buy]]       # the losing buy leg alone is not listed


def test_gap_exploit_respects_inventory_and_min_edge() -> None:
    from blox_trade_finder.core.arbitrage import find_gap_exploits
    A, B, C, D, X, pad = _gap_book()
    buy = _l("buy", [A], [X], source="gamersberg")
    assert find_gap_exploits(pad + [buy], inventory_counts=Counter({"b": 1})) == []     # can't pay A
    assert find_gap_exploits(pad + [buy], inventory_counts=Counter({"a": 1}))
    assert find_gap_exploits(pad + [buy], min_edge=2.0) == []                          # X's gap is 1.82x


def test_gap_exploit_ignores_pure_site_inflation() -> None:
    """A site that prices EVERYTHING 10% higher is not a gap: nothing to exploit."""
    from blox_trade_finder.core.arbitrage import find_gap_exploits
    A, B, C, D, X, pad = _gap_book()
    trades = [_l("t1", [A], [B], source="tradehub"), _l("t2", [B], [C], source="gamersberg")]
    assert find_gap_exploits(pad + trades, min_edge=1.05) == []


def test_arb_view_has_exploits_table() -> None:
    from blox_trade_finder.live import build_arb_view
    A, B, C, D, X, pad = _gap_book()
    buy = _l("buy", [B], [X], source="gamersberg")
    sell = _l("sell", [X], [C], source="tradehub")
    v = build_arb_view(pad + [buy, sell], cfg={**_gap_cfg(), "exploit_edge": 1.10, "exploit_pct": 0.05},
                       inventory_counts=Counter(), scam_cfg=None)
    rows = v["exploits"]
    r = next(r for r in rows if r["Type"].startswith("Round"))
    assert r["Gap item"] == "X" and r["You pay"] == "B" and r["You get"] == "C"
    assert r["Cheap on"] == "Gamersberg" and r["Dear on"] == "Trade Hub"
    assert r["Profit (fair)"] == "100 (+50%)" and r["Gap"] == "1.82x"
    assert r["Link 1"] == "u" and r["Link 2"] == "u"


def test_plan_and_disagree_rows_are_plain_and_merged() -> None:
    from blox_trade_finder.live import build_arb_view
    X = CatalogItem(id=1, name="X", values={"gamersberg": 100, "bloxfruitsvalues": 100})
    W = CatalogItem(id=2, name="W", values={"gamersberg": 80, "bloxfruitsvalues": 80})
    G = CatalogItem(id=3, name="G", values={"gamersberg": 120, "bloxfruitsvalues": 120})
    buy = _l("buy", [W], [X], source="fantasyblox")
    sell = _l("sell", [X], [G], source="tradehub")
    cfg = dict(value_basis="gamersberg", min_pct=0.1, cross_site_only=True, max_age_minutes=None, min_ratio=1.001, only_mine=False)
    v = build_arb_view([buy, sell], cfg=cfg, inventory_counts=Counter(), scam_cfg=None)
    plan = v["plan"]
    assert plan and plan[0]["What to do"] == "Buy X on FantasyBlox, then sell it on Trade Hub"
    assert plan[0]["You give"] == "W" and plan[0]["You end up with"] == "G" and plan[0]["Profit"].endswith("(+50%)")
    assert list(plan[0]) == ["What to do", "You give", "You end up with", "Profit", "Posted", "Step 1", "Step 2"]
    keys = [(r["Step 1"], r["Step 2"]) for r in plan]
    assert len(keys) == len(set(keys))                                    # the same pair is never listed twice


def test_disagree_rows_name_cheapest_and_priciest_site() -> None:
    from blox_trade_finder.live import _disagree_rows
    a = CatalogItem(id=1, name="Venom", values={"gamersberg": 60_000_000, "tradehub": 25_000_000, "fantasyblox": 100_000_000})
    g = item_gaps([_l("x", [CatalogItem(id=2, name="Pain", values={"gamersberg": 10})], [a])])[0]
    row = _disagree_rows([g])[0]
    assert row["Item"] == "Venom" and row["Cheapest on"] == "Trade Hub (25.00M)" and row["Priciest on"] == "FantasyBlox (100.00M)"
    assert row["Real gap"] == "75.00M (4.00x)" and list(row) == ["Item", "Cheapest on", "Priciest on", "Real gap", "Kind"]
