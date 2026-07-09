from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from blox_trade_finder.models import Match


def format_value(v: int) -> str:
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000:
        return f"{sign}{v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{sign}{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{sign}{v / 1_000:.1f}K"
    return f"{sign}{v}"


def format_age(created_at: datetime) -> str:
    """How long ago a listing was posted, e.g. '2h ago', '3d ago'."""
    if not isinstance(created_at, datetime):
        created_at = datetime.fromisoformat(str(created_at))
    seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
    if seconds < 0:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    return f"{int(days)}d ago"


def render_matches(matches: list[Match], console: Console | None = None) -> None:
    """Renders into `console` (defaults to stdout). Pass a file-backed Console
    (see write_matches_to_file) to write plain text into a file instead."""
    console = console or Console()
    if not matches:
        console.print("No matching trades found for your inventory and goals.")
        return

    table = Table(title=f"Blox Fruits Trade Matches ({len(matches)})", show_lines=True)
    table.add_column("Source")
    table.add_column("You Give", style="red")
    table.add_column("You Get", style="green")
    table.add_column("Delta", justify="right")
    table.add_column("Profit %", justify="right")
    table.add_column("Demand", justify="right")
    table.add_column("Verdict")
    table.add_column("Votes", justify="right")
    table.add_column("Confidence", justify="right")
    table.add_column("Age")
    table.add_column("Link", no_wrap=True, overflow="ignore")

    verdict_style = {"win": "green", "fair": "yellow", "loss": "red"}

    for m in matches:
        give_names = ", ".join(i.name for i in m.listing.want)
        get_names = ", ".join(i.name for i in m.listing.give)
        delta_style = "green" if m.delta >= 0 else "red"
        wfl = m.listing.wfl
        votes_str = f"{wfl.get('win', 0)}W/{wfl.get('fair', 0)}F/{wfl.get('lose', 0)}L"
        v_style = verdict_style.get(m.verdict, "white")

        table.add_row(
            m.listing.source,
            give_names,
            get_names,
            f"[{delta_style}]{format_value(m.delta)}[/{delta_style}]",
            f"{m.profit_pct:+.0%}",
            str(m.demand),
            f"[{v_style}]{m.verdict.upper()}[/{v_style}]",
            votes_str,
            f"{m.confidence}%",
            format_age(m.listing.created_at),
            m.listing.url,
        )

    console.print(table)


def write_matches_to_file(matches: list[Match], path: Path) -> None:
    """Writes the ranked matches as plain text (no ANSI color codes) to `path`,
    overwriting any previous run's output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(f"Blox Fruits Trade Finder — results for {datetime.now(timezone.utc).isoformat()}\n\n")
        file_console = Console(file=f, width=220, no_color=True, force_terminal=False)
        render_matches(matches, console=file_console)
