# Goals reference

Every setting you can put in `config/goals.json` (or override with a CLI flag), what it does, its
type, and its default. See `config/goals.example.json` for a filled-in template with the same
explanations inline as JSON comments.

JSON has no `nil` — its equivalent is `null`. Any setting below can be set to `null` (or just left
out of the file) to mean "off, not used."

---

### `any`
- **Type:** boolean. **Default:** `false`. **CLI:** `--any`
- The override switch. If `true`, every other setting in this file is ignored completely. The
  tool just shows every trade you can physically make with your current inventory (i.e. you own
  everything the poster wants), ranked best-first. It does **not** bypass the game's own 40%
  Beli-balance rule (see below) — that's a hard game-engine constraint, not a preference, so it
  always applies no matter what.
- Use this first, before adding filters, to sanity-check the tool is finding anything at all.

### `value_basis`
- **Type:** one of `"gamersberg"`, `"fruityblox"`, `"bloxfruit"`, `"bloxfruitsvalues"`.
  **Default:** `"gamersberg"`. **CLI:** `--basis`
- Which site's trade-value numbers to use when computing profit/loss on a trade. This is a
  **community-estimated trade value**, different from the real in-game Beli price (see the Beli
  rule below, which always uses the real game price regardless of this setting).
- If your chosen source has no value recorded for a given item, the tool automatically falls back
  to whichever other source does have a number for it. You don't need to change this unless you
  specifically distrust one source's numbers.
- Items sourced from bloxfruitsvalues.com are cross-checked against Gamersberg's own catalog by
  name, so `"gamersberg"` (the default) uses Gamersberg's real number for those items too, not just
  bloxfruitsvalues.com's own self-reported one — this matters because those can disagree
  significantly, and it's easy to otherwise think you're seeing Gamersberg-priced numbers when
  you're actually seeing the other site's.

### `min_profit`
- **Type:** integer or `null`. **Default:** `null`. **CLI:** `--min-profit`
- Minimum value gained, in raw value units (of whichever `value_basis` you picked). Example:
  `10000000` means the trade must net you at least +10,000,000 value. `null` = no minimum.

### `min_profit_pct`
- **Type:** float or `null`. **Default:** `null`. **CLI:** `--min-profit-pct`
- Minimum profit as a fraction. Example: `0.1` means the trade must be worth at least +10% more
  than what you're giving up. `null` = no minimum.

### `min_get_value`
- **Type:** integer or `null`. **Default:** `null`.
- Minimum total value of what you'd *receive*, regardless of profit margin. Useful if you only
  care about high-value trades even at breakeven. `null` = no minimum.

### `max_give_value`
- **Type:** integer or `null`. **Default:** `null`.
- Maximum total value of what you'd have to *give up*. Useful to avoid trades that require
  parting with something you consider too valuable, even if the deal is profitable. `null` = no
  maximum.

### `any_fair`
- **Type:** boolean. **Default:** `false`. **CLI:** `--any-fair`
- If `true`, also allow trades with zero or positive delta even when no profit filter is set
  above (i.e. "don't lose value" — not necessarily "gain" value). If `false`, this allowance isn't
  added (other filters, if any, still apply as normal).

### `min_demand`
- **Type:** integer 0–10 or `null`. **Default:** `null`. **CLI:** `--min-demand`
- Minimum demand of the item(s) you'd receive. Higher demand = easier to re-trade later. `null` =
  no minimum.

### `want_item`
- **Type:** string, list of strings, or `null`. **Default:** `null`. **CLI:** `--want` (repeatable)
- Only show trades where you'd receive one of these exact item name(s). A single string
  (`"Kitsune"`) requires that one item; a list (`["Kitsune", "Yeti"]`) matches a trade giving
  *any one* of them — not all of them at once. On the CLI, repeat the flag to build a list:
  `--want Kitsune --want Yeti`. `null` = don't require any specific item.

### `want_item_include_permanent`
- **Type:** boolean. **Default:** `true`. **CLI:** `--exclude-permanent-want-matches` (turns it off)
- When `true` (the default), wanting `"Kitsune"` also matches a trade giving `"Permanent Kitsune"`
  — the assumption is that if you'd be happy with the fruit, you'd probably also be happy with its
  Permanent version. Set to `false` if you specifically only want the exact name(s) you listed
  (e.g. you already own a Permanent one and only want the Physical version, or vice versa).

### `exclude_lose_wfl`
- **Type:** boolean. **Default:** `false`.
- If `true`, skip trades where the community's "Lose" votes outnumber "Win" + "Fair" votes
  combined (Gamersberg only — bloxfruitsvalues.com trades don't carry this vote data, so this
  filter never excludes anything from that source).

### `min_confidence`
- **Type:** integer 0–100 or `null`. **Default:** `null`. **CLI:** `--min-confidence`
- Minimum trust score. See the **Confidence column** section below for exactly what this measures
  and why it exists — it directly targets suspicious trades (e.g. a common fruit "for" a rare
  Limited item with an inflated, unverifiable price) that can otherwise dominate the results.
  `null` = no minimum, but consider setting this to at least `50` if you want to filter out
  low-trust noise by default.

### `max_age_hours`
- **Type:** float or `null`. **Default:** `null` (disabled). **CLI:** `--max-age-hours`
- Drop listings posted more than this many hours ago. Example: `24` means only trades posted in
  the last day. `null` = no age limit — a listing's age still shows up indirectly through the
  Confidence column (freshness), but won't be filtered out by itself unless you set this.

### `max_qty_per_fruit`
- **Type:** integer or `null`. **Default:** `null` (disabled). **CLI:** `--max-qty-per-fruit`
- Blocks a trade if accepting it would leave you owning more than this many copies of any single
  fruit it gives you. Example: with `1`, a trade that gives you a Dough is blocked if you already
  own 1 Dough (1 owned + 1 received = 2 > 1) — with `3`, that same trade is fine, and you could
  keep accepting Dough trades up to 3 total. This cap applies **per fruit independently**: a value
  of `3` means up to 3 of *each* fruit, not a shared budget of 3 across everything. A single trade
  that gives you 2 of the same fruit at once counts both toward the cap. `null` = no cap.

### `limit`
- **Type:** integer. **Default:** `25`. **CLI:** `--limit`
- Max number of ranked results written out. Results are ranked by **absolute value delta**
  (highest profit first, in raw value units), not by profit percentage — a trade that nets
  +10,000,000 value outranks one that's +90% on a tiny item.

---

## The 40% Beli-balance rule (always on, not a goal)

Blox Fruits' own in-game trade menu refuses to let a trade go through if the two sides' total
**real in-game dealer Beli price** differ by more than 40%. This is enforced automatically on
every scan — it isn't a setting in this file because it isn't a preference, it's a fact about
whether the game will even let the trade happen.

This uses the actual Beli stock price (the cost to buy that fruit from the in-game dealer), never
a trade site's estimated value — those are two different numbers. If neither side of a trade has
a known Beli price (e.g. you're trading only Permanent fruit variants or accessories, which aren't
sold by the dealer for Beli), there's nothing to check, so it doesn't block the trade.

---

## The Verdict column (always computed, not a goal)

Every match gets a **Verdict** of `WIN`, `FAIR`, or `LOSS` — this is not a community opinion, it's
computed fresh using the exact same formula found in Gamersberg's own calculator's client code:

```
r = (give_value - get_value) / max(give_value, get_value) * 100

verdict = "FAIR" if -25 <= r <= 25
          "LOSS" if r > 25   (you're giving up more than you'd receive)
          "WIN"  if r < -25  (you'd receive more than you're giving up)
```

`give_value`/`get_value` here **always use Gamersberg's own recorded value specifically** —
never whatever `value_basis` you picked above for the Delta/Profit % columns. That's deliberate:
Gamersberg's calculator only ever judges a trade by Gamersberg's own numbers, so the Verdict
mirrors exactly what their calculator would say for the same trade, regardless of which basis
you're using to rank results. This is also a separate signal from the **Votes** column
(`3W/1F/0L`), which is other traders' opinions on Gamersberg listings (bloxfruitsvalues.com trades
don't have community votes at all, so they only get the computed Verdict).

---

## The Confidence column (always computed, not a goal — but filterable via `min_confidence`)

Confidence (0–100%) is how much to trust a trade's numbers, blended from four things:

- **Value-source agreement (30%)** — do the different value sources roughly agree on each item's
  worth? Wide disagreement (or only one source having any data at all) lowers this.
- **Listing freshness (20%)** — how much of the listing's lifetime is left before it expires.
- **Community vote volume (15%)** — how many Win/Fair/Lose votes the listing has (Gamersberg only;
  0 for bloxfruitsvalues.com trades, which don't have this feature).
- **Beli-verifiability (35%, the largest factor)** — can the 40% Beli-balance rule (above) actually
  be checked for this trade? If either side has no known in-game Beli price, this is 0.

That last factor exists because of a real pattern found in live data: trades involving
"Limited"-rarity items (collectibles with no in-game dealer price, only a community-submitted
value) can show wildly inflated numbers — e.g. a common Mythical fruit "worth" billions when
matched against a Limited, a trade essentially nobody would actually honor. Those trades can't be
Beli-checked at all, so they're capped at a low confidence rather than scored as if they were as
trustworthy as an ordinary fruit-for-fruit trade. If you're seeing suspiciously good trades that
look too good to be true, set `min_confidence` to 50 or higher.
