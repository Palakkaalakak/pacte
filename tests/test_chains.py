from collections import Counter
from datetime import datetime, timedelta, timezone

from blox_trade_finder.core.chains import find_chains
from blox_trade_finder.models import CatalogItem, Listing

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _item(name: str, value: int, i: int) -> CatalogItem:
    return CatalogItem(id=i, name=name, values={"gamersberg": value})


X, Y, Z = _item("X", 10, 1), _item("Y", 12, 2), _item("Z", 15, 3)


def _l(id_: str, wants: CatalogItem, gives: CatalogItem, age_min: float = 1) -> Listing:
    return Listing(
        id=id_, source="gamersberg", url=f"u/{id_}", poster_name="p", poster_rating=1.0,
        give=[gives], want=[wants], wfl={}, created_at=NOW - timedelta(minutes=age_min),
    )


def test_chain_cycle_profit() -> None:
    # Hold X: X->Y, Y->Z, Z->X would be a cycle; here X->Y->Z gains value.
    ls = [_l("a", X, Y), _l("b", Y, Z)]
    chains = find_chains(ls, Counter({"x": 1}), now=NOW)
    best = chains[0]
    assert best.items == ["X", "Y", "Z"]
    assert best.profit == 5


def test_chain_drops_old_listing() -> None:
    ls = [_l("a", X, Y), _l("b", Y, Z, age_min=9)]
    chains = find_chains(ls, Counter({"x": 1}), now=NOW, max_age_minutes=5)
    assert all(len(c.steps) == 1 for c in chains)
    assert find_chains(ls, Counter({"x": 1}), now=NOW, max_age_minutes=10)[0].items == ["X", "Y", "Z"]


def test_cycle_closes_back_to_start() -> None:
    ls = [_l("a", X, Y), _l("b", Y, Z), _l("c", Z, X)]
    chains = find_chains(ls, Counter({"x": 1}), now=NOW, target_names={"x"})
    assert any(c.is_cycle and c.items == ["X", "Y", "Z", "X"] for c in chains)
