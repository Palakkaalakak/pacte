from unittest.mock import MagicMock

import httpx
import pytest

from blox_trade_finder.sources.bloxfruitsvalues import BloxFruitsValuesSource


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> BloxFruitsValuesSource:
    src = BloxFruitsValuesSource()
    monkeypatch.setattr("blox_trade_finder.sources.bloxfruitsvalues.get_or_fetch", lambda key, ttl, fetch, fresh=False: fetch())
    return src


def test_fetch_listings_raw_skips_item_that_fails_and_keeps_the_rest(
    source: BloxFruitsValuesSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_fetch_for_name(name: str) -> list[dict]:
        if name == "Broken Item":
            request = httpx.Request("GET", "https://bloxfruitsvalues.com/api/v1/tradeads/bloxfruits/all")
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError("server error 500", request=request, response=response)
        return [{"id": f"trade-{name}"}]

    monkeypatch.setattr(source, "_fetch_for_name", fake_fetch_for_name)

    result = source.fetch_listings_raw(item_names=["Good Item", "Broken Item", "Another Good Item"])

    ids = {t["id"] for t in result}
    assert ids == {"trade-Good Item", "trade-Another Good Item"}


def test_fetch_listings_raw_returns_empty_when_no_item_names(source: BloxFruitsValuesSource) -> None:
    assert source.fetch_listings_raw(item_names=None) == []
    assert source.fetch_listings_raw(item_names=[]) == []


def test_fetch_listings_raw_calls_on_item_done_for_every_item_including_failures(
    source: BloxFruitsValuesSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_fetch_for_name(name: str) -> list[dict]:
        if name == "Broken Item":
            request = httpx.Request("GET", "https://bloxfruitsvalues.com/api/v1/tradeads/bloxfruits/all")
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError("server error 500", request=request, response=response)
        return [{"id": f"trade-{name}"}]

    monkeypatch.setattr(source, "_fetch_for_name", fake_fetch_for_name)

    done: list[str] = []
    source.fetch_listings_raw(
        item_names=["Good Item", "Broken Item"], on_item_done=lambda name: done.append(name)
    )
    assert done == ["Good Item", "Broken Item"]
