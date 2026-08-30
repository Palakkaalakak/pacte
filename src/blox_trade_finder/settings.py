"""One-file user settings: SETTINGS.json at the repo root.

Friendly single file that replaces watcher config + inventory + goals.
Supports // comment lines (stripped before JSON parsing) so the file can
carry its own tutorial. If SETTINGS.json exists, the watcher uses it and
ignores the old config files entirely.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from blox_trade_finder.emailer import EmailConfig
from blox_trade_finder.models import Goals, Inventory, InventoryEntry
from blox_trade_finder.rules import AlertRule

SETTINGS_FILENAME = "SETTINGS.json"


def _strip_comments(text: str) -> str:
    """Remove lines whose first non-space characters are // (full-line
    comments only, so URLs containing // inside values are safe), and
    forgive trailing commas before } or ] — hand-editing on github.com
    produces those all the time and they must not break the scanner."""
    text = "\n".join(line for line in text.splitlines() if not re.match(r"\s*//", line))
    # Remove trailing commas: a comma followed only by whitespace and a
    # closing brace/bracket. Safe because "," never precedes }/] in values.
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def _rule_from_friendly(raw: dict, index: int) -> AlertRule:
    """Map friendly SETTINGS.json alert keys onto an AlertRule."""
    def millions(key: str) -> int | None:
        v = raw.get(key)
        return int(v * 1_000_000) if v else None

    verdicts: list[str] = []
    if raw.get("only_win_trades"):
        verdicts = ["win"]

    # "instant": true is the friendly way to say "email immediately, don't
    # batch" — it overrides email_every_minutes.
    frequency = int(raw.get("email_every_minutes", 0) or 0)
    if raw.get("instant"):
        frequency = 0

    return AlertRule(
        name=str(raw.get("name") or f"Alert {index + 1}"),
        enabled=bool(raw.get("enabled", True)),
        frequency_minutes=frequency,
        min_profit=millions("min_profit_millions"),
        min_profit_pct=(raw["min_profit_percent"] / 100) if raw.get("min_profit_percent") else None,
        min_get_value=millions("min_value_received_millions"),
        max_give_value=millions("max_value_given_millions"),
        gives_items=[str(x) for x in raw.get("trade_gives", [])],
        wants_items=[str(x) for x in raw.get("trade_wants", [])],
        include_permanent=bool(raw.get("include_permanent", True)),
        verdicts=verdicts,
        min_confidence=raw.get("min_confidence"),
        min_demand=raw.get("min_demand"),
        sources=[str(x) for x in raw.get("sources", [])],
    )


def load_settings(path: Path):
    """Parse SETTINGS.json -> (WatcherConfig, snapshot dir with generated
    inventory/goals files). Returns the ready WatcherConfig."""
    from blox_trade_finder.watcher import WatcherConfig  # avoid circular import

    data = json.loads(_strip_comments(path.read_text(encoding="utf-8")))

    # --- inventory: {"Fruit name": quantity} ---
    own = data.get("i_own") or {}
    if not isinstance(own, dict) or not own:
        raise ValueError('SETTINGS.json: "i_own" must list at least one item, e.g. {"Kitsune": 1}')
    inventory = Inventory(items=[
        InventoryEntry(name=str(name), qty=int(qty)) for name, qty in own.items() if int(qty) > 0
    ])

    # --- goals: which trades count as a match at all ---
    goals = Goals(
        any=False,
        value_basis="gamersberg",
        any_fair=True,
        min_profit=(int(data["min_profit_millions"] * 1_000_000)
                    if data.get("min_profit_millions") else None),
        max_qty_per_fruit=int(data.get("max_of_each_fruit_to_give", 1) or 0) or None,
        exclude_lose_wfl=bool(data.get("skip_community_voted_lose", False)),
        limit=1000,
    )

    # --- alert rules ---
    rules = [_rule_from_friendly(r, i) for i, r in enumerate(data.get("alerts", []))]

    # hunted_fruits -> one instant rule (simplest possible alert)
    hunted = [str(x) for x in data.get("hunted_fruits", [])]

    # --- email ---
    email = None
    to_addr = str(data.get("send_alerts_to") or "").strip()
    if to_addr:
        email = EmailConfig(provider="formsubmit", to_addrs=[to_addr])

    # Write generated inventory/goals snapshots next to the cache.
    gen_dir = Path(".cache") / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    inv_path = gen_dir / "inventory.json"
    goals_path = gen_dir / "goals.json"
    inv_path.write_text(json.dumps(inventory.model_dump(), indent=2), encoding="utf-8")
    goals_path.write_text(json.dumps(goals.model_dump(), indent=2), encoding="utf-8")

    config = WatcherConfig(
        inventory_path=str(inv_path),
        goals_path=str(goals_path),
        scan_interval_minutes=int(data.get("scan_every_minutes", 10) or 10),
        digest_interval_minutes=int(data.get("digest_every_minutes", 30) or 30),
        alert_items=hunted,
        rules=rules,
        sources=data.get("sources") or ["gamersberg", "bloxfruitsvalues"],
        send_empty_digest=False,
        max_matches_per_email=int(data.get("max_trades_per_email", 40) or 40),
        email=email,
    )

    names = [r.name for r in config.rules]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f'SETTINGS.json: two alerts share the same "name": {dupes}')
    return config
