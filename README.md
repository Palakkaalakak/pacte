# Blox Fruits Trade Finder

Scans live trade feeds from [Gamersberg](https://www.gamersberg.com/blox-fruits/trading) and
[bloxfruitsvalues.com](https://bloxfruitsvalues.com/trading) and finds listings that are good deals
for you, based on your inventory and goals.

Both sites are scanned via their internal (undocumented) backend APIs — not official/public APIs.
See the plan doc for details and risk notes.

## Setup

```
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt -e .
```

## Usage

1. Copy `config/inventory.example.json` to `config/inventory.json` and list what you own.
   Item names must exactly match the catalog (case-insensitive) — check with `--list-catalog`
   below. A misspelled or slightly-off name (e.g. an item that doesn't exist under that name)
   won't error, it'll just silently match nothing for that item — the tool warns about this
   at startup if it spots a name it can't resolve, with suggestions.

   Gamersberg tracks **Permanent** fruit variants as genuinely separate items with different
   values (e.g. "Permanent Portal" vs "Portal") — set `"variant": "Permanent"` on an inventory
   entry (or just write the full "Permanent X" name yourself) so matching targets the right one.
   bloxfruitsvalues.com stores both variants' values on one shared item entry, but usually marks
   which one a specific trade actually offers — when it does, that's picked up automatically and
   the item is labeled "Permanent X" in the output too.
2. Copy `config/goals.example.json` to `config/goals.json` and set your goals. See
   [GOALS.md](GOALS.md) for what every setting does.
3. Run:

```
python -m blox_trade_finder --inventory config/inventory.json --goals config/goals.json
```

A live progress bar (plus an overall bar spanning the whole scan) tracks each phase: catalog
fetch, Gamersberg trade feed, bloxfruitsvalues.com — with a real per-item counter, since that's
usually the slowest step — matching, and writing results, so you can see where it is instead of
staring at a blank terminal.

The Gamersberg trade feed and bloxfruitsvalues.com queries run **concurrently** (two unrelated
hosts, each with its own independent rate limit — no reason to wait on one before starting the
other), so a scan's wall-clock time is roughly the slower of the two rather than both added
together. Verified live: a 20-item inventory took ~2m48s total, matching the ~2m46s the slower
(bloxfruitsvalues.com) step alone took — the ~1 minute Gamersberg trade-feed fetch happened for
free, hidden inside that wait.

Results are **not** printed to the terminal — every run gets its own folder,
`output/Iteration_N/` (N auto-increments, so past runs are never overwritten), containing:
- `trades_found.txt` — the ranked matches table
- `debug.txt` — a full trace of what the tool did: every fetch, cache hit/miss, per-item query,
  and per-listing feasibility/goal decision. If something looks wrong (e.g. "no trades found"),
  this file shows exactly why, listing by listing, instead of it being a black box.

The terminal just prints a short summary telling you which `Iteration_N/` folder to look in.

Each match's **Verdict** column (Win/Fair/Loss) is computed fresh using the same formula
Gamersberg's own calculator uses, always on Gamersberg's own recorded value (regardless of which
`value_basis` you're ranking by) — not the community vote counts (those are shown separately in
the **Votes** column, e.g. `3W/1F/0L`). See [GOALS.md](GOALS.md) for the exact formula.

Useful flags: `--any` (ignore every goal filter, just show anything you can feasibly trade for —
good first sanity check), `--fresh` (bypass cache), `--want "Dragon"` (must give this item; repeat
the flag — `--want Dragon --want Kitsune` — to match trades giving *any one* of several items;
by default this also matches the Permanent version of each — pass `--exclude-permanent-want-matches`
to require an exact name match instead), `--min-profit 10000000`, `--min-profit-pct 0.1`,
`--min-demand 7`, `--min-confidence 50` (drop low-trust trades — see below), `--max-age-hours 24`
(skip listings older than this), `--max-qty-per-fruit 1` (don't suggest trades that'd leave you
owning more than this many of any one fruit), `--any-fair`, `--limit 10`, `--output PATH` /
`--debug-log PATH` (skip the Iteration_N folder and write to an exact path instead).

**A note on trust:** bloxfruitsvalues.com's much larger trade pool means it can surface trades
with huge, implausible profit numbers — usually because one side is a rare "Limited" item with an
inflated, community-submitted (and unverifiable) value rather than a real dealer-priced fruit.
The **Confidence** column scores this directly (see [GOALS.md](GOALS.md)), and it's the reason
those trades often rank above ordinary Gamersberg ones by raw profit % alone. If you want to
filter that noise out entirely, set `--min-confidence 50` (or higher).

Browse the raw Gamersberg catalog (128 items, values, demand) with:

```
python -m blox_trade_finder --list-catalog
```

bloxfruitsvalues.com doesn't have a separate catalog browse — its trade ads carry full item
value/demand data inline, so it's only queried per-item, filtered to trades that want something
in your inventory (that site hosts 200k+ trade ads across all its games; paging through all of
them isn't practical).

Every trade is also checked against Blox Fruits' own **40% Beli-balance rule** — the game itself
refuses trades where the two sides' real in-game dealer Beli value differ by more than 40%. This
always applies, regardless of your goals (see [GOALS.md](GOALS.md) for details).

## Tests

```
pytest
```
