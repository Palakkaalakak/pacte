from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

ValueBasis = Literal["gamersberg", "fruityblox", "bloxfruit", "bloxfruitsvalues"]


class Variant(str, Enum):
    PHYSICAL = "Physical"
    PERMANENT = "Permanent"
    SCROLL = "Scroll"
    GAMEPASS = "Gamepass"
    NONE = "None"


class CatalogItem(BaseModel):
    id: int
    name: str
    tags: list[str] = Field(default_factory=list)
    rarity: str | None = None
    type: str | None = None
    demand: int = 0
    trend: str = "unknown"
    values: dict[str, int] = Field(default_factory=dict)
    robux_price: int = 0
    # Real in-game dealer/stock Beli price (not a trade-site value estimate). 0 for
    # items with no dealer price (Permanent fruit variants, accessories, skins,
    # scrolls) — those don't count toward the game's 40% trade-balance rule.
    beli_price: int = 0
    image: str | None = None

    def value(self, basis: ValueBasis) -> int:
        """Value for `basis`, falling back to any other populated source if the
        chosen basis has no data for this item (0). Different sources populate
        different keys in `values` (e.g. gamersberg items never have a
        'bloxfruitsvalues' key and vice versa), so the fallback is generic
        rather than a fixed key order — but iterates sorted keys so the result
        is deterministic rather than depending on insertion order."""
        preferred = self.values.get(basis, 0)
        if preferred > 0:
            return preferred
        for key in sorted(self.values):
            if self.values[key] > 0:
                return self.values[key]
        return 0


class Catalog(BaseModel):
    items: list[CatalogItem]
    version: int
    fetched_at: datetime

    @property
    def by_id(self) -> dict[int, CatalogItem]:
        return {i.id: i for i in self.items}

    @property
    def by_name(self) -> dict[str, CatalogItem]:
        return {i.name.lower(): i for i in self.items}


class Listing(BaseModel):
    id: str
    source: str
    url: str
    calculator_url: str | None = None
    poster_name: str
    poster_rating: float
    give: list[CatalogItem]
    want: list[CatalogItem]
    wfl: dict[str, int]
    created_at: datetime
    expires_at: datetime | None = None


class Goals(BaseModel):
    any: bool = False  # if true, ignore every filter below entirely — see matcher.find_matches
    value_basis: ValueBasis = "gamersberg"
    min_profit: int | None = None
    min_profit_pct: float | None = None
    min_demand: int | None = None
    want_item: str | list[str] | None = None  # one name, or a list — matches a trade giving ANY of them
    want_item_include_permanent: bool = True  # also match "Permanent X" for each name in want_item
    min_get_value: int | None = None
    max_give_value: int | None = None
    any_fair: bool = False
    exclude_lose_wfl: bool = False
    min_confidence: int | None = None  # 0-100, drop trades below this trust score (see GOALS.md)
    max_age_hours: float | None = None  # drop listings posted more than this many hours ago
    max_qty_per_fruit: int | None = None  # cap on owned+received copies of any single fruit, per fruit (see GOALS.md)
    limit: int = 25


class InventoryEntry(BaseModel):
    name: str
    variant: str | None = None
    qty: int = 1


class Inventory(BaseModel):
    items: list[InventoryEntry]


class Match(BaseModel):
    listing: Listing
    give_value: int
    get_value: int
    delta: int
    profit_pct: float
    demand: int
    confidence: int
    score: float
    reasons: list[str]
    verdict: str  # "win" / "fair" / "loss" — computed via Gamersberg's own calculator formula
