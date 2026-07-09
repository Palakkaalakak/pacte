from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from blox_trade_finder.models import Catalog, CatalogItem

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_catalog() -> Catalog:
    items = [
        CatalogItem(
            id=57, name="Kitsune", tags=["Physical"], rarity="Mythical", demand=10, trend="stable",
            values={"gamersberg": 680_000_000, "fruityblox": 165_000_000, "bloxfruit": 490_000_000},
        ),
        CatalogItem(
            id=92, name="Yeti", tags=["Physical"], rarity="Mythical", demand=6, trend="stable",
            values={"gamersberg": 5_000_000, "fruityblox": 0, "bloxfruit": 4_800_000},
        ),
        CatalogItem(
            id=71, name="Shadow", tags=["Physical"], rarity="Mythical", demand=5, trend="dropping",
            values={"gamersberg": 2_900_000, "fruityblox": 2_000_000, "bloxfruit": 0},
        ),
    ]
    return Catalog(items=items, version=272, fetched_at=datetime.now(timezone.utc))


@pytest.fixture
def sample_trades_raw() -> list[dict]:
    with (FIXTURES / "trades_sample.json").open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def catalog_sse_text() -> str:
    return (FIXTURES / "catalog_sse_sample.txt").read_text(encoding="utf-8")
