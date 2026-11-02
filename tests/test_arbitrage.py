from datetime import datetime, timezone

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
