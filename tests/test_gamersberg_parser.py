from blox_trade_finder.sources.gamersberg import _parse_catalog_sse, _to_catalog_item


def test_parse_catalog_sse_extracts_all_items_and_stops_at_end(catalog_sse_text: str) -> None:
    items = _parse_catalog_sse(catalog_sse_text)
    assert len(items) == 3
    assert [i["name"] for i in items] == ["Kitsune", "Yeti", "Shadow"]


def test_parse_catalog_sse_ignores_non_data_lines() -> None:
    raw = "event: ping\n\ndata: {\"id\": 1, \"name\": \"Test\"}\n\ndata: [END]\n"
    items = _parse_catalog_sse(raw)
    assert len(items) == 1
    assert items[0]["name"] == "Test"


def test_to_catalog_item_maps_value_fields_and_lowercases_trend() -> None:
    raw = {
        "id": 57, "name": "Kitsune", "tags": ["Physical"], "rarity": "Mythical", "type": "Zoan",
        "demand": 10, "indicator": "Stable",
        "gamersbergvalue": 680_000_000, "fruitybloxvalue": 165_000_000, "bloxfruitvalue": 490_000_000,
        "robuxprice": 4000, "image": "https://asset.gamersberg.com/x.webp",
    }
    item = _to_catalog_item(raw)
    assert item.id == 57
    assert item.trend == "stable"
    assert item.values == {"gamersberg": 680_000_000, "fruityblox": 165_000_000, "bloxfruit": 490_000_000}


def test_to_catalog_item_handles_missing_optional_fields() -> None:
    raw = {"id": 1, "name": "Minimal Item"}
    item = _to_catalog_item(raw)
    assert item.tags == []
    assert item.demand == 0
    assert item.trend == "unknown"
    assert item.values == {"gamersberg": 0, "fruityblox": 0, "bloxfruit": 0}
