# Blox Fruits trade-ad sites: research (2026-11)

Goal: find more places that publish live trade ads, two popular and two smaller ones that are
easy to integrate. Each candidate was probed over plain HTTP (no login, no browser) and the
response checked for structured trade data.

## Integrated

| Site | Size | How the data is exposed | Notes |
|---|---|---|---|
| **FantasyBlox** (fantasyblox.com) | Popular. Trade ids are past 1.3 million, a new ad every few seconds | JSON `GET /api/trades?offset=N`, 15 ads/page, `nextOffset`/`hasMore`, newest first | FantasyBlox has no page per ad (it keeps trade-search state in the browser), so links open the poster's profile (`/profile/<roblox id>`). Items carry only `name` + `mode` (`permanent`/`normal`). Ads of `kind: inventory` are skipped. Uses placeholder items such as "Offers"/"Adds", which are dropped. |
| **Blox Fruits Trade Hub** (bloxfruitstradehub.com) | Popular. About 3,800 live ads | JSON `GET /api/trades`, returns every active ad newest first (ignores paging params, multi-MB) | Full item records with `side` (`offering`/`requesting`), `quantity`, `isPermanent`. The payload also contains private user fields (billing ids); the adapter reads only the public display name. Polled at most every 15 s. |
| **TradeBloxFruit** (tradebloxfruit.com) | Small (about 10 live ads) | JSON `GET /api/trade-ads?page=N` with `total_pages` | Cleanest schema: `offering`/`requesting` lists with `name`, `mode`, `qty`, per-item values. Created time is an epoch number. |
| **BloxFruitsValues.gg** (bloxfruitsvalues.gg) | Smaller sister-style site | No JSON route. The server-rendered `/trades` page embeds about 60 newest ads (Supabase rows) in its streamed Next.js payload | Parsed with a string-aware bracket matcher. Fragile if the site changes framework; failure is contained (that site just yields no listings). |

All four are resolved against the Gamersberg catalog by item name, so every site is priced with
the same numbers and results stay comparable. Spelling differences are handled by an alias table
(`Dragon (West)` → `West Dragon`, `Magnet` → `Magnet Fruit`, `Hellfire` → `Hellfire Gas`, ...). A
trade containing an item that can't be resolved (or a placeholder like "Or"/"Adds") is skipped
rather than guessed.

## Periphery (opt-in toggle)

| Site | Notes |
|---|---|
| **BloxFruitsAI** (bloxfruitsai.com) | Tiny board (about 7 ads) embedded in the `/trading` page; names are lowercase slugs and free text ("Dragon and or Dough"), so only the clean ads resolve (4 of 7 in testing). Enabled with the "Include periphery sites" toggle; not part of the default site set. |

| **BloxValues.net** (bloxvalues.net) | WordPress site running the same trade-ad plugin as TradeBloxFruit, exposed at `/wp-json/bloxcalc/v1/trade-ads` (20/page, newest first, per-item values, no `status` field, naive UTC timestamps). 26 live ads when tested. Opt-in. |

## Checked, not usable

| Site | Why |
|---|---|
| bloxfruits.trade | Trade offers need a login (`/api/offers` answers "missing bearer token"); no open ad feed. |
| bloxfruittrading.com | A copy of another game's site template (its text talks about fish); no usable feed. |
| bloxfruittradecalculator.com | Calculator only, no trade-ad board. |
| TradeKitsune (tradekitsune.com/bloxfruits) | Next.js app; its trade list is not served from any open route I could find. |
| BloxVaults (bloxvaults.com/trading) | Static page with a post form; no feed endpoint found. |

## Not integrated

| Site | Why |
|---|---|
| **FruityBlox** (fruityblox.com) | Popular, but behind a Cloudflare bot challenge (HTTP 403 "Just a moment…"). Getting past it would mean evading the site's protection, so it is left out. |
| **Traderie** (traderie.com) | Same Cloudflare challenge. |
| bloxfruitsai.com | Trade board with names only, the ads are embedded in the page; usable but lower value than the four above. |
| blox-fruits.com, bloxfruits.gg, 123Demands, Fandom wiki | Wikis / value lists / calculators, no trade-ad feed. |

## Using them

Pick sites in **4. Where to look** (multiselect). Gamersberg and bloxfruitsvalues.com stay the
default; the four new ones are opt-in. In Live mode with **⚡ Constant**, every site gets its own
polling loop paced to what that site can take (FantasyBlox 1 s, TradeBloxFruit and
BloxFruitsValues.gg 3 s, Trade Hub 15 s).

## Validation (2026-11-02)

For each new site I read raw ads straight from its API, built an inventory containing exactly what
the poster asks for, and checked the scanner returns that ad with the same items on both sides.
Result: 8 of 11 ads came back with exactly the raw items; the other 3 were correctly rejected by
the in-game 40% Beli-balance rule (the game itself would block those trades). A Gravity-only
inventory returned no trades from any site, as it should.

Short name `Hellfire` (very common on FantasyBlox) is aliased to `Hellfire Gas` (confirmed by the user).
