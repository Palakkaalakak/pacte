"""Four more Blox Fruits trade-ad sites, each wrapped in the same small adapter shape.

Researched 2026-11 (see docs/trading-sites-research.md). All four expose their trade ads
without a login or bot challenge. Items are resolved against the Gamersberg catalog by
name, so every site is valued with the same numbers and results are directly comparable.

Popular, high-volume
  * fantasyblox      – fantasyblox.com, JSON feed `/api/trades` (ids past 1.3 million).
  * tradehub         – bloxfruitstradehub.com, JSON feed `/api/trades` (thousands of live ads).
Smaller, but very clean to integrate
  * tradebloxfruit   – tradebloxfruit.com, JSON `/api/trade-ads` with per-item values.
  * bfvgg            – bloxfruitsvalues.gg, ads embedded in the server-rendered /trades page.

Not included on purpose: FruityBlox and Traderie sit behind a Cloudflare bot challenge
("Just a moment…"); getting past that would mean evading their protection, so we don't.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from blox_trade_finder.http_client import RateLimiter, USER_AGENT, request_with_retry
from blox_trade_finder.sources.age import page_is_too_old, to_epoch
from blox_trade_finder.models import Catalog, CatalogItem, Listing

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ shared helpers
# How other sites spell items vs Gamersberg's catalog: name -> (regular name, permanent name).
ALIASES: dict[str, tuple[str, str]] = {
    "dragon (west)": ("West Dragon", "Permanent West Dragon"),
    "dragon (east)": ("East Dragon", "Permanent East Dragon"),
    "magnet": ("Magnet Fruit", "Permanent Magnet"),
    "hellfire": ("Hellfire Gas", "Permanent Hellfire Gas"),
}


def _resolve(name: str, permanent: bool, by_name: dict[str, CatalogItem]) -> CatalogItem | None:
    name = (name or "").strip()
    if not name:
        return None
    alias = ALIASES.get(name.lower())
    if alias:
        return by_name.get(alias[1 if permanent else 0].lower())
    if permanent and not name.lower().startswith("permanent "):
        name = f"Permanent {name}"
    return by_name.get(name.lower())


def parse_money(text) -> int:
    """'500m' -> 500_000_000, '4.56b' -> 4_560_000_000, 'N/A'/None -> 0."""
    if isinstance(text, (int, float)):
        return int(text)
    raw = str(text or "").strip().lower().replace(",", "")
    mult = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
    try:
        if raw and raw[-1] in mult:
            return int(float(raw[:-1]) * mult[raw[-1]])
        return int(float(raw))
    except ValueError:
        return 0


def _with_value(item: CatalogItem, site: str, value: int) -> CatalogItem:
    """A copy of the catalog item that also carries THIS site's own number under `site`,
    so the same item can be compared across sites (value gaps, per-site arbitrage)."""
    if value <= 0:
        return item
    return item.model_copy(update={"values": {**item.values, site: int(value)}})


def _parse_time(value) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _listing(site: str, ad_id, base_url: str, poster: str, give, want, created) -> Listing | None:
    if not give or not want:
        return None
    return Listing(
        id=f"{site}:{ad_id}", source=site,
        url=f"{base_url}{'&' if '?' in base_url else '?'}ad={ad_id}",  # unique per ad
        poster_name=poster or "unknown", poster_rating=0.0,
        give=give, want=want, wfl={"win": 0, "fair": 0, "lose": 0},
        created_at=_parse_time(created),
    )


def _items(entries, by_name, name_of, perm_of, qty_of, site=None, own_value_of=None) -> list[CatalogItem] | None:
    """Resolve every entry or return None (a trade with an unknown item can't be valued).
    `own_value_of(entry, permanent)` supplies the site's own number for the item, if it has one."""
    out: list[CatalogItem] = []
    for e in entries:
        perm = perm_of(e)
        item = _resolve(name_of(e), perm, by_name)
        if item is None:
            return None
        if own_value_of is not None:
            item = _with_value(item, site, own_value_of(e, perm))
        out.extend([item] * max(1, int(qty_of(e) or 1)))
    return out


class _Site:
    id = ""
    label = ""
    poll_seconds = 2.0  # constant mode: minimum gap between polls of this site
    page_url = ""

    def __init__(self, request_interval: float = 0.5) -> None:
        self._client = httpx.Client(
            base_url=self.page_url.split("/", 3)[0] + "//" + self.page_url.split("/")[2],
            headers={"user-agent": USER_AGENT}, timeout=12.0,
        )
        self._rl = RateLimiter(request_interval)
        # Fast retries: the next poll is seconds away, so a failing request is just skipped.
        self._retry = {"max_retries": 2, "backoff_base": 0.25}

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, **params) -> httpx.Response:
        resp = request_with_retry(self._client, "GET", path, params=params or None,
                                  rate_limiter=self._rl, **self._retry)
        resp.raise_for_status()
        return resp

    def fetch_raw(self, latest: bool = False, max_age_minutes: float | None = None) -> list[dict]:  # pragma: no cover
        raise NotImplementedError

    def build(self, raw: list[dict], catalog: Catalog) -> list[Listing]:  # pragma: no cover
        raise NotImplementedError


# ------------------------------------------------------------------ FantasyBlox
_FB_VALUES: dict = {"at": 0.0, "map": {}}


def _fantasyblox_values(site: "FantasyBlox") -> dict[tuple[str, bool], int]:
    """FantasyBlox's own value list (/api/values), cached for 10 minutes: (name, permanent) -> value."""
    if time.time() - _FB_VALUES["at"] < 600 and _FB_VALUES["map"]:
        return _FB_VALUES["map"]
    try:
        rows = site._get("/api/values").json().get("overrides", [])
    except Exception as exc:  # values are a bonus: never break the trade feed over them
        logger.warning("fantasyblox values unavailable: %s", exc)
        return _FB_VALUES["map"]
    m: dict[tuple[str, bool], int] = {}
    for r in rows:
        name = (r.get("itemName") or "").strip().lower()
        m[(name, False)] = parse_money(r.get("value"))
        m[(name, True)] = parse_money(r.get("permValue"))
    _FB_VALUES.update(at=time.time(), map=m)
    return m


class FantasyBlox(_Site):
    id, label, poll_seconds = "fantasyblox", "FantasyBlox", 1.0
    page_url = "https://fantasyblox.com/games/blox-fruits/trade"  # no per-ad page exists; ?ad= only keeps links unique
    PAGE = 15
    MAX_PAGES = 20  # full pass = newest 300 ads

    def fetch_raw(self, latest: bool = False, max_age_minutes: float | None = None) -> list[dict]:
        out: list[dict] = []
        offset = 0
        for _ in range(1 if latest else self.MAX_PAGES):
            body = self._get("/api/trades", offset=offset).json()
            trades = body.get("trades", [])
            out.extend(t for t in trades if t.get("kind") == "normal")
            if not body.get("hasMore") or page_is_too_old(trades, "created_at", max_age_minutes):
                break
            offset = body.get("nextOffset", offset + self.PAGE)
        return out

    def build(self, raw, catalog):
        by_name = {i.name.lower(): i for i in catalog.items}
        vals = _fantasyblox_values(self) if raw else {}
        own = lambda e, perm: vals.get(((e.get("name") or "").strip().lower(), bool(perm)), 0)
        out = []
        for t in raw:
            give = _items(t.get("offering") or [], by_name, lambda e: e.get("name"),
                          lambda e: e.get("mode") == "permanent", lambda e: e.get("qty") or e.get("quantity"),
                          self.id, own)
            want = _items(t.get("wants") or [], by_name, lambda e: e.get("name"),
                          lambda e: e.get("mode") == "permanent", lambda e: e.get("qty") or e.get("quantity"),
                          self.id, own)
            if give is None or want is None:
                continue
            # FantasyBlox has no page per ad (its trade page keeps search state in the browser, not
            # in the URL). The poster's profile page is the closest specific link: it opens on
            # that trader, so you can see/contact them. ?ad= keeps each link unique.
            rid = t.get("roblox_id")
            base = f"https://fantasyblox.com/profile/{rid}" if rid else self.page_url
            lst = _listing(self.id, t["id"], base, t.get("username"), give, want, t["created_at"])
            if lst:
                out.append(lst)
        return out


# ------------------------------------------------------------------ Blox Fruits Trade Hub
class TradeHub(_Site):
    id, label, poll_seconds = "tradehub", "Blox Fruits Trade Hub", 15.0  # one big (multi-MB) response
    page_url = "https://bloxfruitstradehub.com/trading"

    def fetch_raw(self, latest: bool = False, max_age_minutes: float | None = None) -> list[dict]:
        # The endpoint ignores paging params and returns every active ad, newest first; trim the
        # tail we don't need before any further processing.
        data = self._get("/api/trades").json()
        if max_age_minutes:
            cutoff = time.time() - max_age_minutes * 60
            keep = len(data)
            for i, ad in enumerate(data):
                ts = to_epoch(ad.get("createdAt"))
                if ts is not None and ts < cutoff:
                    keep = i
                    break
            data = data[:keep]
        return data[:300] if latest else data

    def build(self, raw, catalog):
        by_name = {i.name.lower(): i for i in catalog.items}
        out = []
        for t in raw:
            if t.get("status") != "active":
                continue
            rows = t.get("tradeItems") or []
            def side(s):
                return _items([r for r in rows if r.get("side") == s], by_name,
                              lambda r: (r.get("item") or {}).get("name"),
                              lambda r: bool(r.get("isPermanent")), lambda r: r.get("quantity"),
                              self.id,
                              # the site quotes values in millions
                              lambda r, perm: (r.get("item") or {}).get("permanentValue" if perm else "value", 0) * 1_000_000 if (r.get("item") or {}).get("permanentValue" if perm else "value") else 0)
            give, want = side("offering"), side("requesting")
            if give is None or want is None:
                continue
            u = t.get("user") or {}  # only the public display fields are used
            lst = _listing(self.id, t["id"], self.page_url, u.get("displayName") or u.get("username"),
                           give, want, t["createdAt"])
            if lst:
                out.append(lst)
        return out


# ------------------------------------------------------------------ TradeBloxFruit
class TradeBloxFruit(_Site):
    id, label, poll_seconds = "tradebloxfruit", "TradeBloxFruit", 3.0
    page_url = "https://tradebloxfruit.com/trading"

    def fetch_raw(self, latest: bool = False, max_age_minutes: float | None = None) -> list[dict]:
        out: list[dict] = []
        page = 1
        while page <= (1 if latest else 5):
            body = self._get("/api/trade-ads", page=page).json()
            ads = body.get("ads", [])
            out.extend(a for a in ads if a.get("status") == "active")
            if page >= (body.get("total_pages") or 1) or page_is_too_old(ads, "created_at", max_age_minutes):
                break
            page += 1
        return out

    def build(self, raw, catalog):
        by_name = {i.name.lower(): i for i in catalog.items}
        out = []
        for a in raw:
            own = lambda e, perm: e.get("value") or 0
            give = _items(a.get("offering") or [], by_name, lambda e: e.get("name"),
                          lambda e: e.get("mode") == "permanent", lambda e: e.get("qty"), self.id, own)
            want = _items(a.get("requesting") or [], by_name, lambda e: e.get("name"),
                          lambda e: e.get("mode") == "permanent", lambda e: e.get("qty"), self.id, own)
            if give is None or want is None:
                continue
            lst = _listing(self.id, a["id"], self.page_url, a.get("username"), give, want, a["created_at"])
            if lst:
                out.append(lst)
        return out


# ------------------------------------------------------------------ bloxfruitsvalues.gg
def _extract_json_array(text: str, key: str) -> list:
    """Pull `"key":[ ... ]` out of a Next.js server-rendered page (escaped JSON in the
    streamed payload). String-aware bracket matching, so braces inside notes are safe."""
    u = text.replace('\\"', '"').replace("\\\\", "\\")
    m = re.search(rf'"{re.escape(key)}"\s*:\s*\[', u)
    if not m:
        return []
    i = m.end() - 1
    depth, in_str, esc = 0, False, False
    for j in range(i, len(u)):
        ch = u[j]
        if in_str:
            esc = (not esc) and ch == "\\"
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(u[i:j + 1])
    return []


class BloxFruitsValuesGG(_Site):
    id, label, poll_seconds = "bfvgg", "BloxFruitsValues.gg", 3.0
    page_url = "https://bloxfruitsvalues.gg/trades"

    def fetch_raw(self, latest: bool = False, max_age_minutes: float | None = None) -> list[dict]:
        # Server-rendered page that embeds the newest ~60 ads (a single page: nothing to cut short).
        return _extract_json_array(self._get("/trades").text, "ads")

    def build(self, raw, catalog):
        by_name = {i.name.lower(): i for i in catalog.items}
        out = []
        for a in raw:
            if a.get("status") != "open":
                continue
            rows = a.get("trade_ad_items") or []
            def side(s):
                return _items([r for r in rows if r.get("side") == s], by_name,
                              lambda r: (r.get("fruits") or {}).get("name"),
                              lambda r: bool(r.get("is_permanent")), lambda r: r.get("quantity"),
                              self.id,
                              lambda r, perm: (r.get("fruits") or {}).get("permanent_value" if perm else "physical_value") or 0)
            give, want = side("offering"), side("wanting")
            if give is None or want is None:
                continue
            lst = _listing(self.id, a["id"], self.page_url, (a.get("profiles") or {}).get("username"),
                           give, want, a["created_at"])
            if lst:
                out.append(lst)
        return out


EXTRA_SITES: dict[str, type[_Site]] = {
    s.id: s for s in (FantasyBlox, TradeHub, TradeBloxFruit, BloxFruitsValuesGG)
}
