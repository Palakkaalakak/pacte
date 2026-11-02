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
