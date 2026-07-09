from __future__ import annotations

from abc import ABC, abstractmethod

from blox_trade_finder.models import Catalog


class ValueSource(ABC):
    id: str
    ttl_seconds: int

    @abstractmethod
    def fetch_catalog(self, *, fresh: bool = False) -> Catalog: ...


class TradeSource(ABC):
    id: str
    ttl_seconds: int

    @abstractmethod
    def fetch_listings_raw(
        self, *, item_names: list[str] | None = None, fresh: bool = False
    ) -> list[dict]:
        """Raw trades from this source. `item_names` (your inventory) is a hint,
        not a hard filter contract: a full-feed source (like Gamersberg) can
        ignore it and return everything; a source too large to page through in
        full (like bloxfruitsvalues.com's 200k+ trade ads) uses it to run one
        targeted query per owned item instead."""
        ...
