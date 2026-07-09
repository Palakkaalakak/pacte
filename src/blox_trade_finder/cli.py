from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from blox_trade_finder.core.matcher import find_matches
from blox_trade_finder.core.normalize import (
    build_listings,
    build_listings_bfv,
    check_inventory_names,
    inventory_counts,
)
from blox_trade_finder.models import Goals, Inventory
from blox_trade_finder.sources.bloxfruitsvalues import BloxFruitsValuesSource
from blox_trade_finder.sources.gamersberg import GamersbergSource
from blox_trade_finder.ui.table import format_value, write_matches_to_file

OUTPUT_BASE_DIR = Path("output")
LIST_CATALOG_DEBUG_LOG_PATH = OUTPUT_BASE_DIR / "debug.txt"  # --list-catalog is a lookup, not a run — no iteration folder


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="blox-trade-finder",
        description="Scan live Gamersberg + bloxfruitsvalues.com trade feeds for deals that fit your inventory and goals.",
    )
    p.add_argument("--inventory", type=Path, help="Path to inventory JSON file")
    p.add_argument("--goals", type=Path, help="Path to goals JSON file")
    p.add_argument("--fresh", action="store_true", help="Bypass cache, force a live re-fetch")
    p.add_argument(
        "--any",
        action="store_true",
        help="Ignore every goal filter — show any trade you can make (matches one or more inventory items)",
    )
    p.add_argument(
        "--basis",
        choices=["gamersberg", "fruityblox", "bloxfruit", "bloxfruitsvalues"],
        help="Override value basis",
    )
    p.add_argument(
        "--want", type=str, action="append",
        help="Only show trades that give this item. Repeat to match ANY of several, "
        "e.g. --want Kitsune --want Yeti",
    )
    p.add_argument(
        "--exclude-permanent-want-matches", action="store_true",
        help="By default, wanting 'Kitsune' also matches trades giving 'Permanent Kitsune' "
        "(on by default — this flag turns that off, requiring an exact name match)",
    )
    p.add_argument("--min-profit", type=int, help="Minimum absolute value delta")
    p.add_argument("--min-profit-pct", type=float, help="Minimum profit fraction, e.g. 0.1 for +10%%")
    p.add_argument("--min-demand", type=int, help="Minimum demand (0-10) of items you'd receive")
    p.add_argument(
        "--min-confidence", type=int,
        help="Minimum trust score 0-100 (drops trades with unverifiable Beli data or weak value agreement)",
    )
    p.add_argument(
        "--max-age-hours", type=float,
        help="Drop listings posted more than this many hours ago (disabled by default)",
    )
    p.add_argument(
        "--max-qty-per-fruit", type=int,
        help="Block a trade if you'd end up owning more than this many of any single fruit it gives you "
        "(applies per fruit independently; disabled by default)",
    )
    p.add_argument("--any-fair", action="store_true", help="Include any trade with delta >= 0")
    p.add_argument("--limit", type=int, help="Max results to show")
    p.add_argument("--list-catalog", action="store_true", help="Print the full item catalog and exit")
    p.add_argument(
        "--output", type=Path, default=None,
        help="Where to write the ranked matches. Default: a fresh output/Iteration_N/trades_found.txt each run.",
    )
    p.add_argument(
        "--debug-log", type=Path, default=None,
        help="Where to write the full debug log of this run. Default: output/Iteration_N/debug.txt alongside --output.",
    )
    return p


def _next_iteration_dir(base: Path = OUTPUT_BASE_DIR) -> Path:
    """Each run gets its own output/Iteration_N/ folder (N auto-increments) so
    past runs' results and debug traces are never overwritten — you can compare
    Iteration_1 against Iteration_2 after changing your inventory or goals."""
    base.mkdir(parents=True, exist_ok=True)
    existing = [
        int(p.name[len("Iteration_"):])
        for p in base.iterdir()
        if p.is_dir() and p.name.startswith("Iteration_") and p.name[len("Iteration_"):].isdigit()
    ]
    next_n = max(existing, default=0) + 1
    iteration_dir = base / f"Iteration_{next_n}"
    iteration_dir.mkdir()
    return iteration_dir


def _setup_debug_log(path: Path) -> None:
    """Every fetch, cache hit/miss, per-listing feasibility/goal decision, and
    skip reason gets written here at DEBUG level — the point is there's no
    black box: this file is a full trace of what the tool actually did."""
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(path),
        filemode="w",
        encoding="utf-8",  # Windows' default open() encoding is locale-dependent (cp1252), not UTF-8
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _load_inventory(path: Path | None) -> Inventory:
    if path is None:
        print("No --inventory given; assuming empty inventory (no trades will be feasible).", file=sys.stderr)
        return Inventory(items=[])
    with path.open("r", encoding="utf-8") as f:
        return Inventory.model_validate(json.load(f))


def _load_goals(path: Path | None, args: argparse.Namespace) -> Goals:
    data = {}
    if path is not None:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    goals = Goals.model_validate(data)

    if args.any:
        goals.any = True
    if args.basis is not None:
        goals.value_basis = args.basis
    if args.want is not None:
        goals.want_item = args.want
    if args.exclude_permanent_want_matches:
        goals.want_item_include_permanent = False
    if args.min_profit is not None:
        goals.min_profit = args.min_profit
    if args.min_profit_pct is not None:
        goals.min_profit_pct = args.min_profit_pct
    if args.min_demand is not None:
        goals.min_demand = args.min_demand
    if args.min_confidence is not None:
        goals.min_confidence = args.min_confidence
    if args.max_age_hours is not None:
        goals.max_age_hours = args.max_age_hours
    if args.max_qty_per_fruit is not None:
        goals.max_qty_per_fruit = args.max_qty_per_fruit
    if args.any_fair:
        goals.any_fair = True
    if args.limit is not None:
        goals.limit = args.limit
    return goals


def _print_catalog(source: GamersbergSource, fresh: bool) -> None:
    catalog = source.fetch_catalog(fresh=fresh)
    console = Console()
    table = Table(title=f"Blox Fruits Catalog (v{catalog.version}, {len(catalog.items)} items)", show_lines=True)
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Tags")
    table.add_column("Demand", justify="right")
    table.add_column("Trend")
    table.add_column("Gamersberg", justify="right")
    table.add_column("Fruityblox", justify="right")
    table.add_column("Bloxfruit", justify="right")
    for item in sorted(catalog.items, key=lambda i: -i.values.get("gamersberg", 0)):
        table.add_row(
            str(item.id),
            item.name,
            ", ".join(item.tags),
            str(item.demand),
            item.trend,
            format_value(item.values.get("gamersberg", 0)),
            format_value(item.values.get("fruityblox", 0)),
            format_value(item.values.get("bloxfruit", 0)),
        )
    console.print(table)


def main() -> None:
    args = _build_arg_parser().parse_args()

    if args.list_catalog:
        debug_log_path = args.debug_log or LIST_CATALOG_DEBUG_LOG_PATH
        _setup_debug_log(debug_log_path)
        logging.getLogger("blox_trade_finder.cli").info("mode: --list-catalog")
        gamersberg = GamersbergSource()
        try:
            _print_catalog(gamersberg, args.fresh)
        finally:
            gamersberg.close()
        return

    # A fresh Iteration_N/ folder per run, unless the user explicitly overrode
    # --output and/or --debug-log (in which case we respect their exact path
    # for whichever one they specified).
    iteration_dir = _next_iteration_dir() if (args.output is None or args.debug_log is None) else None
    output_path = args.output if args.output is not None else iteration_dir / "trades_found.txt"
    debug_log_path = args.debug_log if args.debug_log is not None else iteration_dir / "debug.txt"

    _setup_debug_log(debug_log_path)
    logger = logging.getLogger("blox_trade_finder.cli")

    gamersberg = GamersbergSource()
    bfv = BloxFruitsValuesSource()
    try:
        inventory = _load_inventory(args.inventory)
        goals = _load_goals(args.goals, args)
        logger.info("inventory: %s", [(e.name, e.qty) for e in inventory.items])
        logger.info("goals: %s", goals.model_dump())

        item_names = [entry.name for entry in inventory.items]
        progress_console = Console(stderr=True)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=progress_console,
        ) as progress:
            # Overall bar spans the 5 phases below — it's a rough "how far along
            # am I" indicator, not a precisely-timed measure (some phases take
            # a second, others a minute), but it's the one thing you can glance
            # at without reading any phase description.
            t_overall = progress.add_task("Overall progress", total=5)

            # Gamersberg's trade feed (often the slowest single step — up to 60
            # paginated requests) and bloxfruitsvalues.com's per-item queries hit
            # two completely unrelated hosts, so there's no politeness reason to
            # run them one after another — each has its own rate limiter (see
            # http_client.RateLimiter), so run them concurrently while the
            # (fast) Gamersberg catalog fetch happens on the main thread.
            t_catalog = progress.add_task("Fetching Gamersberg catalog...", total=None)
            t_gb_trades = progress.add_task("Fetching Gamersberg trade feed...", total=None)
            t_bfv = (
                progress.add_task("Querying bloxfruitsvalues.com...", total=len(item_names))
                if item_names
                else None
            )

            def _fetch_gb_trades() -> list[dict]:
                raw = gamersberg.fetch_listings_raw(fresh=args.fresh)
                progress.update(
                    t_gb_trades, total=1, completed=1,
                    description=f"Gamersberg trade feed fetched ({len(raw)} trades)",
                )
                progress.update(t_overall, advance=1)
                return raw

            def _fetch_bfv() -> list[dict]:
                if not item_names:
                    progress.update(t_overall, advance=1)
                    return []

                def _on_item_done(name: str) -> None:
                    progress.update(t_bfv, advance=1, description=f"Querying bloxfruitsvalues.com ({name})")

                raw = bfv.fetch_listings_raw(item_names=item_names, fresh=args.fresh, on_item_done=_on_item_done)
                progress.update(
                    t_bfv, description=f"bloxfruitsvalues.com queried ({len(raw)} trade ad(s) found)"
                )
                progress.update(t_overall, advance=1)
                return raw

            with ThreadPoolExecutor(max_workers=2) as executor:
                f_gb_trades = executor.submit(_fetch_gb_trades)
                f_bfv = executor.submit(_fetch_bfv)

                catalog = gamersberg.fetch_catalog(fresh=args.fresh)
                progress.update(t_catalog, total=1, completed=1, description="Gamersberg catalog fetched")
                progress.update(t_overall, advance=1)

                name_warnings = check_inventory_names(inventory, catalog)
                for warning in name_warnings:
                    progress_console.print(f"[warn] {warning}")

                gamersberg_raw = f_gb_trades.result()
                bfv_raw = f_bfv.result()

            t_match = progress.add_task("Matching trades...", total=None)
            listings = build_listings(gamersberg_raw, catalog) + build_listings_bfv(bfv_raw, catalog)
            inv_counts = inventory_counts(inventory)
            matches = find_matches(listings, inv_counts, goals)
            progress.update(t_match, total=1, completed=1, description=f"Matched {len(matches)} trade(s)")
            progress.update(t_overall, advance=1)

            t_write = progress.add_task("Writing results...", total=None)
            write_matches_to_file(matches, output_path)
            progress.update(t_write, total=1, completed=1, description="Results written")
            progress.update(t_overall, advance=1)

        logger.info("wrote %d match(es) to %s", len(matches), output_path)

        print(f"Found {len(matches)} match(es). Results written to {output_path}")
        if name_warnings:
            print(f"{len(name_warnings)} inventory item(s) had name warnings — see stderr above.")
        print(f"Full run trace: {debug_log_path}")
    finally:
        gamersberg.close()
        bfv.close()
