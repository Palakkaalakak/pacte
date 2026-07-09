from blox_trade_finder.models import CatalogItem


def test_value_prefers_requested_basis_when_present() -> None:
    item = CatalogItem(id=1, name="X", values={"gamersberg": 100, "bloxfruitsvalues": 200})
    assert item.value("gamersberg") == 100
    assert item.value("bloxfruitsvalues") == 200


def test_value_falls_back_to_any_other_nonzero_source() -> None:
    # gamersberg has no data for this item, but bloxfruitsvalues does
    item = CatalogItem(id=1, name="X", values={"gamersberg": 0, "bloxfruitsvalues": 200})
    assert item.value("gamersberg") == 200


def test_value_is_zero_when_no_source_has_data() -> None:
    item = CatalogItem(id=1, name="X", values={"gamersberg": 0, "bloxfruitsvalues": 0})
    assert item.value("gamersberg") == 0
