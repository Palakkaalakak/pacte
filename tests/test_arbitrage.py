from datetime import datetime, timezone

from blox_trade_finder.core.arbitrage import find_gap_trades, item_gaps
from blox_trade_finder.models import CatalogItem, Listing


def _it(name, gb, bfv, i=1):
    return CatalogItem(id=i, name=name, values={"gamersberg": gb, "bloxfruitsvalues": bfv})


def _l(id_, want, give):
    return Listing(id=id_, source="gamersberg", url="u", poster_name="p", poster_rating=1.0,
                   give=give, want=want, wfl={}, created_at=datetime.now(timezone.utc))


def test_item_gaps_ranks_by_gap() -> None:
    ls = [_l("a", [_it("A", 10, 10)], [_it("B", 100, 200, 2)])]
    gaps = item_gaps(ls)
    assert [g.name for g in gaps] == ["B"] and gaps[0].higher_on == "bloxfruitsvalues"


def test_gap_trade_consensus_and_single_site() -> None:
    cons = _l("c", [_it("A", 10, 10)], [_it("B", 15, 14, 2)])      # wins on both
    gap = _l("g", [_it("A", 10, 10)], [_it("C", 9, 20, 3)])        # wins only on bfv
    none = _l("n", [_it("A", 10, 10)], [_it("D", 9, 9, 4)])         # loses on both
    res = find_gap_trades([cons, gap, none], min_pct=0.1)
    assert [t.listing.id for t in res] == ["c", "g"]
    assert res[0].consensus and not res[1].consensus and res[1].edge_site == "bloxfruitsvalues"
