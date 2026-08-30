# Blox Fruits Trade Finder

Scans live trade feeds from [Gamersberg](https://www.gamersberg.com/blox-fruits/trading) and
[bloxfruitsvalues.com](https://bloxfruitsvalues.com/trading) and finds listings that are good deals
for you, based on your inventory and goals.

Both sites are scanned via their internal (undocumented) backend APIs — not official/public APIs.
See the plan doc for details and risk notes.

## ⭐ Quick start: edit ONE file — `SETTINGS.json`

Everything you'd normally want to change lives in **[`SETTINGS.json`](SETTINGS.json)** at the
repo root: your email, your fruits, hunted fruits, and alert rules — with a full tutorial in
comments at the top of the file. Edit it on github.com (pencil icon → commit) and the cloud
scanner picks it up on its next run. When `SETTINGS.json` exists, the watcher uses it and
ignores every other config file. The sections below about `config/*.json` are only for
advanced/legacy setups.

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

## Choosing sources & deep scanning

By default both sites are scanned. Restrict with:

```
python -m blox_trade_finder --inventory config/inventory.json --goals config/goals.json --sources gamersberg
```

(`--sources gamersberg | bloxfruitsvalues | both`.)

**Deep Gamersberg scanning is on by default.** The Gamersberg feed serves only 12 trades per
page, newest-first, with no server-side filters (verified live) — a shallow fetch sees only a
tiny slice of it. The deep scan pages through up to 400 pages (~4,800 trades) and stores every
trade it has ever seen in `.cache/gamersberg_trade_store.json`. Trades expire 7 days after
posting and are pruned automatically. On subsequent scans it stops paginating as soon as it hits
3 consecutive pages of already-known trades, so after the first full scan only the new head of
the feed is fetched — fast *and* comprehensive. Disable with `--no-deep` for the old quick
shallow fetch.

## Web UI (Streamlit)

```
streamlit run streamlit_app.py
```

- **Saved inventories**: build an inventory in "Build my own", give it a name, hit 💾 Save.
  It appears under "My saved inventories", where you can preview, ✏️ edit (reopens it in the
  builder), or 🗑️ delete it. Saved to `config/user_inventories/` (gitignored).
- **Source toggle**: "Where to look" — Both sites / Gamersberg only / bloxfruitsvalues.com only.
- **Watcher panel**: the "📧 Automatic scanning & email alerts" expander at the bottom saves a
  `config/watcher.json` (plus snapshots of your current inventory/goals) for the watcher below.

## Watcher: automatic scanning + email alerts

The watcher is a long-running process that:

- **scans every 10 minutes** (configurable) with the same deep-scan pipeline,
- **emails a digest every 30 minutes** (configurable) of all new matching trades,
- **emails instantly** the moment a trade gives one of your `alert_items` (hunted fruits —
  "Dragon" automatically also matches "Permanent Dragon"),
- remembers what it already emailed about (`.cache/watcher_seen.json`), so restarts don't
  re-alert on the same trades.

Setup:

1. Copy `config/watcher.example.json` to `config/watcher.json` and fill it in (or use the
   Streamlit watcher panel to generate it). For Gmail, create an
   [App Password](https://myaccount.google.com/apppasswords) — your normal password won't work.
   `config/watcher.json` is gitignored because it contains that password.
2. Run:

```
python -m blox_trade_finder.watcher --config config/watcher.json
```

`--once` runs a single scan cycle and exits (good for testing). If no `email` block is
configured, the watcher runs in dry-run mode and prints would-be emails to the console.
Logs go to `output/watcher.log`.

### Alert rules: what to email about & how often

Beyond the plain digest and `alert_items`, you can define **alert rules** — each rule has its
own conditions and its own delivery frequency. Manage them in the Streamlit watcher panel
("🔔 Alert rules") or write them straight into `config/watcher.json`:

```json
"rules": [
  {
    "name": "Kitsune deals - instant",
    "frequency_minutes": 0,
    "gives_items": ["Kitsune"],
    "verdicts": ["win"]
  },
  {
    "name": "Big profit - hourly batch",
    "frequency_minutes": 60,
    "min_profit": 50000000,
    "min_confidence": 70
  }
]
```

Per-rule fields (all conditions optional; unset = don't care; set conditions are ANDed):

| Field | Meaning |
| --- | --- |
| `name` | Unique rule name (appears in the email subject as `[name]`) |
| `enabled` | `false` disables the rule without deleting it (default `true`) |
| `frequency_minutes` | **0 = instant email** the moment a matching trade is found; **N = batched** — at most one email every N minutes with everything queued since the last one |
| `min_profit` | Minimum profit (value received − value given) |
| `min_profit_pct` | Minimum profit as a fraction of value given (`0.25` = +25%) |
| `min_get_value` | Minimum total value the trade gives you |
| `max_give_value` | Maximum total value you have to give up |
| `gives_items` | Trade must GIVE you at least one of these items |
| `wants_items` | Trade must ASK FOR at least one of these items |
| `include_permanent` | `"Dragon"` also matches `"Permanent Dragon"` (default `true`) |
| `verdicts` | Restrict to `"win"` / `"fair"` / `"loss"` (empty = any) |
| `min_confidence` | Minimum value-confidence 0–100 |
| `min_demand` | Minimum demand 0–10 |
| `sources` | Restrict to `"gamersberg"` / `"bloxfruitsvalues"` (empty = any) |

Notes:

- One trade can trigger **several rules** (you'll get it in each rule's email).
- Trades **no rule claims** still go into the regular digest — rules add to it, they don't
  replace it.
- Batched-rule queues persist to `.cache/watcher_rule_state/`, so the schedule keeps working
  across restarts and across GitHub Actions `--once` runs.
- `alert_items` still works and is treated as an extra instant rule named
  `"Hunted fruits (legacy alert_items)"`.

### Running it continuously

The watcher only scans **while the process is running** — it's a normal Python program, not a
cloud service. Options:

- **Your own PC, left on**: just leave the command above running in a terminal. If the PC
  sleeps or shuts down, scanning stops until you start it again.
- **A cheap VPS (recommended for 24/7)**: any ~$4/month Linux VPS works. Install Python, clone
  the repo, and register it as a systemd service so it survives reboots:

  ```ini
  # /etc/systemd/system/blox-watcher.service
  [Unit]
  Description=Blox Fruits trade watcher
  After=network-online.target

  [Service]
  WorkingDirectory=/home/you/blox-trade-finder
  ExecStart=/home/you/blox-trade-finder/.venv/bin/python -m blox_trade_finder.watcher --config config/watcher.json
  Restart=always
  RestartSec=30

  [Install]
  WantedBy=multi-user.target
  ```

  Then `systemctl enable --now blox-watcher`.

This kind of always-on background process **cannot** run on serverless platforms like
Cloudflare Pages/Workers (no long-running processes) — it needs a real machine.

### Free 24/7 cloud option: GitHub Actions

You don't need your PC on at all — GitHub can run the scans for free on a schedule.
`.github/workflows/watcher.yml` is already set up: every ~10 minutes GitHub spins up a runner,
restores the watcher's state (trade store, seen-tracker, digest queue — all persisted across
runs), executes one scan cycle (`--once`), emails any instant alerts, sends the digest if 30+
minutes have passed since the last one, and saves state back.

One-time setup:

1. Push this repo to GitHub. **Public repos get unlimited free Actions minutes**; private repos
   get 2,000 free minutes/month (each scan is a few minutes, ~144 runs/day — a public repo is
   the safe choice, but note your inventory/goals are then visible to anyone).
2. Create committable CI copies of your setup (these are just fruit lists — no secrets):
   `config/inventory.ci.json`, `config/goals.ci.json`, and `config/watcher.ci.json` (copy from
   `config/watcher.ci.example.json`; leave `"password": ""`).
3. In the repo: **Settings → Secrets and variables → Actions → New repository secret** —
   name `WATCHER_SMTP_PASSWORD`, value = your Gmail App Password. The watcher reads it from the
   environment, so no password ever lands in git.
4. Check the **Actions** tab — you can also trigger a manual run there ("Run workflow").

Caveats: GitHub cron is best-effort (runs can start a few minutes late or occasionally skip
during busy periods — fine for trade scanning), and GitHub auto-disables schedules in repos with
no commits for 60 days (it emails you first; one click re-enables it).

Other genuinely-free routes if you prefer a real always-on process: **Oracle Cloud Always Free**
(a real forever-free VM — use the systemd unit above) or a **Raspberry Pi / old laptop** at home.

## Tests

```
pytest
```
