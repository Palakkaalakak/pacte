"""Mobile-friendly web UI for Blox Fruits Trade Finder.

No config files, no JSON, no command line — pick a saved setup (or build your
own inventory/goals right here), tap "Find Trades".
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from blox_trade_finder.core.matcher import find_matches
from blox_trade_finder.core.normalize import build_listings, build_listings_bfv, inventory_counts
from blox_trade_finder.models import Goals, Inventory, InventoryEntry
from blox_trade_finder.sources.bloxfruitsvalues import BloxFruitsValuesSource
from blox_trade_finder.sources.gamersberg import GamersbergSource
from blox_trade_finder.ui.table import format_value

PRESETS_DIR = Path(__file__).parent / "config" / "presets"

INVENTORY_PRESETS = {
    "Palakkaalakak's": PRESETS_DIR / "creation_inventory.json",
    "Cscgde's": PRESETS_DIR / "green_lightning_inventory.json",
}
GOALS_PRESETS = {
    "Palakkaalakak's": PRESETS_DIR / "creation_goals.json",
    "Cscgde's": PRESETS_DIR / "green_lightning_goals.json",
}


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_resource(show_spinner=False)
def _catalog_names() -> list[str]:
    source = GamersbergSource()
    try:
        catalog = source.fetch_catalog(fresh=False)
    finally:
        source.close()
    return sorted(item.name for item in catalog.items)


def _posted_ago(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    seconds = max(0, (datetime.now(timezone.utc) - when).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.0f}h ago"
    days = hours / 24
    return f"{days:.0f}d ago"


def _inventory_preview_lines(inventory: Inventory) -> list[str]:
    return [f"{entry.name} x{entry.qty}" for entry in inventory.items]


VALUE_BASIS_LABELS = {
    "gamersberg": "Gamersberg",
    "fruityblox": "FruityBlox",
    "bloxfruit": "BloxFruit Values",
    "bloxfruitsvalues": "bloxfruitsvalues.com",
}


def _goals_preview_lines(goals: Goals) -> list[str]:
    if goals.any:
        lines = ["Show every trade you can physically make — no filters applied."]
        lines.append(f"Value source: {VALUE_BASIS_LABELS.get(goals.value_basis, goals.value_basis)}")
        lines.append(f"Showing up to {goals.limit} result(s)")
        return lines
    lines = []
    if goals.value_basis != "gamersberg":
        lines.append(f"Value source: {VALUE_BASIS_LABELS.get(goals.value_basis, goals.value_basis)}")
    if goals.min_profit:
        lines.append(f"Minimum profit: {format_value(goals.min_profit)}")
    if goals.min_profit_pct:
        lines.append(f"Minimum profit: +{goals.min_profit_pct:.0%}")
    if goals.min_get_value:
        lines.append(f"Minimum value received: {format_value(goals.min_get_value)}")
    if goals.max_give_value:
        lines.append(f"Maximum value given up: {format_value(goals.max_give_value)}")
    if goals.any_fair:
        lines.append("Also include break-even trades (no loss, no big gain)")
    if goals.min_demand:
        lines.append(f"Minimum demand of what you'd receive: {goals.min_demand}/10")
    if goals.want_item:
        names = goals.want_item if isinstance(goals.want_item, list) else [goals.want_item]
        suffix = "" if goals.want_item_include_permanent else " (exact name only, not Permanent variants)"
        lines.append(f"Only trades giving: {', '.join(names)}{suffix}")
    if goals.min_confidence:
        lines.append(f"Minimum trust score: {goals.min_confidence}%")
    if goals.max_age_hours:
        lines.append(f"Ignore listings older than {goals.max_age_hours:.0f} hours")
    if goals.max_qty_per_fruit:
        lines.append(f"Don't suggest owning more than {goals.max_qty_per_fruit} of any one fruit")
    if goals.exclude_lose_wfl:
        lines.append("Skip trades the community mostly voted a loss")
    lines.append(f"Showing up to {goals.limit} result(s)")
    if len(lines) == 1:
        lines.insert(0, "No extra filters — just needs to be a trade you can physically make.")
    return lines


st.set_page_config(page_title="Blox Fruits Trade Finder", page_icon="🍈", layout="centered")

st.title("🍈 Blox Fruits Trade Finder")
st.write("Set up what you own and what you want, then tap **Find Trades**.")

# ---------------------------------------------------------------- inventory
st.header("1. What you own")
inventory_mode = st.radio(
    "Inventory", ["Use a saved setup", "Build my own"], horizontal=True, label_visibility="collapsed"
)

if inventory_mode == "Use a saved setup":
    inventory_choice = st.selectbox("Saved inventory", list(INVENTORY_PRESETS.keys()))
    inventory = Inventory.model_validate(_load_json(INVENTORY_PRESETS[inventory_choice]))
    with st.expander(f"See what's in \"{inventory_choice}\""):
        for line in _inventory_preview_lines(inventory):
            st.write(f"- {line}")
else:
    all_items = _catalog_names()
    owned_names = st.multiselect("Fruits/items you own", all_items)
    entries = []
    if owned_names:
        st.caption("How many of each do you own?")
        for name in owned_names:
            qty = st.number_input(name, min_value=1, value=1, step=1, key=f"qty_{name}")
            entries.append(InventoryEntry(name=name, qty=qty))
    inventory = Inventory(items=entries)

# -------------------------------------------------------------------- goals
st.header("2. What you're looking for")
goals_mode = st.radio(
    "Goals", ["Use a saved setup", "Choose my own"], horizontal=True, label_visibility="collapsed"
)

if goals_mode == "Use a saved setup":
    goals_choice = st.selectbox("Saved goals", list(GOALS_PRESETS.keys()))
    goals = Goals.model_validate(_load_json(GOALS_PRESETS[goals_choice]))
    with st.expander(f"See what \"{goals_choice}\" looks for"):
        for line in _goals_preview_lines(goals):
            st.write(f"- {line}")
else:
    show_any = st.checkbox("Just show me anything I can trade for (skip the filters below)", value=False)
    min_profit_millions = st.slider("Minimum profit (in millions of value)", 0, 200, 0, step=5, disabled=show_any)
    min_profit_pct = st.slider(
        "Minimum profit (%)", 0, 200, 0, step=5,
        help="Trade must be worth at least this much more than what you're giving up.",
        disabled=show_any,
    )
    any_fair = st.checkbox(
        "Also include break-even trades (no loss, no big gain)", value=True, disabled=show_any
    )
    min_demand = st.slider(
        "Minimum demand of what you'd receive (0 = don't care, 10 = very tradeable)", 0, 10, 0,
        disabled=show_any,
    )
    want_names = st.multiselect(
        "Only show trades that give me one of these (optional)", _catalog_names(), disabled=show_any
    )
    want_item_include_permanent = st.checkbox(
        "Also match the Permanent version of anything I want above", value=True,
        disabled=show_any or not want_names,
    )

    with st.expander("Advanced filters"):
        value_basis_label = st.selectbox(
            "Value source (which site's numbers to rank trades by)",
            list(VALUE_BASIS_LABELS.values()),
            index=0,
            disabled=show_any,
        )
        value_basis = next(k for k, v in VALUE_BASIS_LABELS.items() if v == value_basis_label)
        min_get_value_millions = st.slider(
            "Minimum value received (in millions), regardless of profit margin", 0, 500, 0, step=5,
            disabled=show_any,
        )
        max_give_value_millions = st.slider(
            "Maximum value I'm willing to give up (in millions)", 0, 500, 0, step=5,
            help="0 = no limit.",
            disabled=show_any,
        )
        exclude_lose_wfl = st.checkbox(
            "Skip trades the community mostly voted a loss (Gamersberg only)", value=False, disabled=show_any
        )
        min_confidence = st.slider(
            "Minimum trust score (0 = don't care)", 0, 100, 0,
            help="Blends value-source agreement, listing freshness, community votes, and whether the "
            "40% Beli-balance rule could even be checked. Raise this to filter out suspicious trades.",
            disabled=show_any,
        )
        max_age_hours = st.slider(
            "Ignore listings older than this many hours (0 = no limit)", 0, 168, 0,
            disabled=show_any,
        )
        max_qty_per_fruit = st.slider(
            "Don't suggest owning more than this many of any one fruit (0 = no cap)", 0, 20, 0,
            disabled=show_any,
        )
        limit = st.slider("Max results to show", 10, 1000, 200, step=10)

    goals = Goals(
        any=show_any,
        value_basis=value_basis,
        min_profit=min_profit_millions * 1_000_000 if min_profit_millions > 0 else None,
        min_profit_pct=min_profit_pct / 100 if min_profit_pct > 0 else None,
        min_get_value=min_get_value_millions * 1_000_000 if min_get_value_millions > 0 else None,
        max_give_value=max_give_value_millions * 1_000_000 if max_give_value_millions > 0 else None,
        any_fair=any_fair,
        min_demand=min_demand if min_demand > 0 else None,
        want_item=want_names or None,
        want_item_include_permanent=want_item_include_permanent,
        exclude_lose_wfl=exclude_lose_wfl,
        min_confidence=min_confidence if min_confidence > 0 else None,
        max_age_hours=max_age_hours if max_age_hours > 0 else None,
        max_qty_per_fruit=max_qty_per_fruit if max_qty_per_fruit > 0 else None,
        limit=limit,
    )
    with st.expander("See what these goals look for"):
        for line in _goals_preview_lines(goals):
            st.write(f"- {line}")

# ------------------------------------------------------------------- action
find_clicked = st.button("🔎 Find Trades", type="primary", use_container_width=True)

if find_clicked:
    if not inventory.items:
        st.warning("Add at least one item you own first.")
        st.stop()

    gamersberg = GamersbergSource()
    bfv = BloxFruitsValuesSource()
    progress = st.progress(0, text="Starting scan...")
    try:
        item_names = [entry.name for entry in inventory.items]

        progress.progress(5, text="Fetching item catalog...")
        catalog = gamersberg.fetch_catalog(fresh=False)

        progress.progress(15, text="Fetching Gamersberg trade feed in the background...")
        with ThreadPoolExecutor(max_workers=1) as executor:
            f_gamersberg_raw = executor.submit(gamersberg.fetch_listings_raw, fresh=False)

            bfv_raw: list[dict] = []
            if item_names:
                total = len(item_names)

                def _on_item_done(name: str, _count: list[int] = [0]) -> None:
                    _count[0] += 1
                    pct = 15 + int(_count[0] / total * 65)
                    progress.progress(min(pct, 80), text=f"Querying bloxfruitsvalues.com... ({_count[0]}/{total}: {name})")

                bfv_raw = bfv.fetch_listings_raw(item_names=item_names, fresh=False, on_item_done=_on_item_done)

            progress.progress(85, text="Waiting for Gamersberg trade feed...")
            gamersberg_raw = f_gamersberg_raw.result()

        progress.progress(92, text="Matching trades against your goals...")
        listings = build_listings(gamersberg_raw, catalog) + build_listings_bfv(bfv_raw, catalog)
        inv_counts = inventory_counts(inventory)
        matches = find_matches(listings, inv_counts, goals)
        progress.progress(100, text="Done!")
    finally:
        gamersberg.close()
        bfv.close()
    progress.empty()

    st.success(f"Found {len(matches)} matching trade(s).")

    if matches:
        rows = []
        for m in matches:
            rows.append({
                "Source": m.listing.source,
                "You Give": ", ".join(i.name for i in m.listing.want),
                "You Get": ", ".join(i.name for i in m.listing.give),
                "Profit": format_value(m.delta),
                "Profit %": f"{m.profit_pct:+.0%}",
                "Demand": m.demand,
                "Verdict": m.verdict.upper(),
                "Confidence": f"{m.confidence}%",
                "Posted": _posted_ago(m.listing.created_at),
                "Link": m.listing.url,
            })
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={"Link": st.column_config.LinkColumn("Link")},
        )
    else:
        st.info("No trades matched right now. Try loosening your goals, or check back later — trade feeds change constantly.")
