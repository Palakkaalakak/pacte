import json
from datetime import datetime, timezone

from blox_trade_finder.models import Catalog, CatalogItem
from blox_trade_finder.sources.extra_sites import (
    EXTRA_SITES, BloxFruitsValuesGG, FantasyBlox, TradeBloxFruit, TradeHub, _extract_json_array, _resolve,
)


def _cat() -> Catalog:
    names = ["Venom", "Permanent Venom", "Pain", "West Dragon", "Magnet Fruit", "Hellfire Gas"]
    items = [CatalogItem(id=i, name=n, values={"gamersberg": 1000 * (i + 1)}) for i, n in enumerate(names)]
    return Catalog(items=items, version=1, fetched_at=datetime.now(timezone.utc))


def _site(cls):
    return cls.__new__(cls)  # build() needs no network client


def test_four_sites_registered() -> None:
    assert set(EXTRA_SITES) == {"fantasyblox", "tradehub", "tradebloxfruit", "bfvgg"}


def test_aliases_and_permanent_resolution() -> None:
    by = {i.name.lower(): i for i in _cat().items}
    assert _resolve("Dragon (West)", False, by).name == "West Dragon"
    assert _resolve("Magnet", False, by).name == "Magnet Fruit"
    assert _resolve("Hellfire", False, by).name == "Hellfire Gas"
    assert _resolve("Venom", True, by).name == "Permanent Venom"
    assert _resolve("Offers", False, by) is None            # placeholder item -> not a definite trade


def test_fantasyblox_build_skips_unknown_and_inventory() -> None:
    raw = [
        {"id": "1", "kind": "normal", "username": "a", "created_at": "2026-11-02T01:00:00.000Z",
         "offering": [{"name": "Venom", "mode": "permanent"}], "wants": [{"name": "Dragon (West)", "mode": "normal"}]},
        {"id": "2", "kind": "normal", "username": "b", "created_at": "2026-11-02T01:00:00.000Z",
         "offering": [{"name": "Venom", "mode": "normal"}], "wants": [{"name": "Adds", "mode": "normal"}]},
    ]
    out = _site(FantasyBlox).build(raw, _cat())
    assert len(out) == 1 and out[0].give[0].name == "Permanent Venom" and out[0].want[0].name == "West Dragon"
    assert out[0].source == "fantasyblox" and out[0].url.endswith("ad=1")


def test_tradehub_build_uses_sides_and_quantity() -> None:
    raw = [{"id": 5, "status": "active", "createdAt": "2026-11-01T20:00:22.709Z",
            "user": {"displayName": "Kot"},
            "tradeItems": [
                {"side": "offering", "quantity": 2, "isPermanent": False, "item": {"name": "Venom"}},
                {"side": "requesting", "quantity": 1, "isPermanent": False, "item": {"name": "Pain"}}]},
           {"id": 6, "status": "closed", "createdAt": "2026-11-01T20:00:22Z", "tradeItems": []}]
    out = _site(TradeHub).build(raw, _cat())
    assert len(out) == 1 and [i.name for i in out[0].give] == ["Venom", "Venom"] and out[0].poster_name == "Kot"


def test_tradebloxfruit_build_epoch_time() -> None:
    raw = [{"id": 9, "username": "u", "created_at": 1793575833, "offering": [{"name": "Venom", "mode": "regular", "qty": 1}],
            "requesting": [{"name": "Pain", "mode": "regular", "qty": 3}]}]
    out = _site(TradeBloxFruit).build(raw, _cat())
    assert len(out[0].want) == 3 and out[0].created_at.year == 2026


def test_bfvgg_extracts_ads_from_escaped_page_payload() -> None:
    ads = [{"id": "x", "status": "open", "created_at": "2026-11-02T00:00:00+00:00", "note": "has ] and } and [brackets]",
            "profiles": {"username": "p"},
            "trade_ad_items": [
                {"side": "offering", "quantity": 1, "is_permanent": True, "fruits": {"name": "Venom"}},
                {"side": "wanting", "quantity": 1, "is_permanent": False, "fruits": {"name": "Pain"}}]}]
    page = "self.__next_f.push([1,\"" + json.dumps({"ads": ads}).replace("\\", "\\\\").replace('"', '\\"') + "\"])"
    assert _extract_json_array(page, "ads") == ads
    out = _site(BloxFruitsValuesGG).build(ads, _cat())
    assert out[0].give[0].name == "Permanent Venom" and out[0].poster_name == "p"


def test_page_is_too_old_and_fantasyblox_stops_paging() -> None:
    from datetime import timedelta
    from blox_trade_finder.sources.age import page_is_too_old
    now = datetime.now(timezone.utc)
    iso = lambda m: (now - timedelta(minutes=m)).isoformat()
    assert page_is_too_old([{"t": iso(90)}, {"t": iso(70)}], "t", 60)
    assert not page_is_too_old([{"t": iso(90)}, {"t": iso(10)}], "t", 60)      # one young ad keeps the page
    assert not page_is_too_old([{"t": iso(90)}], "t", None)                    # no limit -> never stop
    assert not page_is_too_old([{"nope": 1}], "t", 60)                        # unreadable time -> keep going

    pages = [
        {"trades": [{"id": "1", "kind": "normal", "created_at": iso(5)}], "hasMore": True, "nextOffset": 15},
        {"trades": [{"id": "2", "kind": "normal", "created_at": iso(200)}], "hasMore": True, "nextOffset": 30},
        {"trades": [{"id": "3", "kind": "normal", "created_at": iso(300)}], "hasMore": True, "nextOffset": 45},
    ]
    calls = []

    class Resp:
        def __init__(self, body): self._b = body
        def json(self): return self._b

    site = _site(FantasyBlox)
    site._get = lambda path, offset=0: (calls.append(offset), Resp(pages[offset // 15]))[1]
    out = site.fetch_raw(max_age_minutes=60)
    assert calls == [0, 15] and [t["id"] for t in out] == ["1", "2"]            # page 3 (all older) never requested


def test_fantasyblox_links_open_the_posters_profile() -> None:
    raw = [{"id": "7", "kind": "normal", "username": "a", "roblox_id": "123", "created_at": "2026-11-02T01:00:00.000Z",
            "offering": [{"name": "Venom", "mode": "normal"}], "wants": [{"name": "Pain", "mode": "normal"}]}]
    site = _site(FantasyBlox)
    import blox_trade_finder.sources.extra_sites as mod
    mod._FB_VALUES.update(at=1e18, map={("x", False): 1})   # skip the values request
    out = site.build(raw, _cat())
    assert out[0].url == "https://fantasyblox.com/profile/123?ad=7"
