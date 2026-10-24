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
    assert [g.name for g in gaps] == ["B"] and gaps[0].higher_on == "bloxfruitsvalues"


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
