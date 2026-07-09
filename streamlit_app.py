"""Mobile-friendly web UI for Blox Fruits Trade Finder.

No config files, no JSON, no command line — pick a saved setup (or build your
own inventory/goals right here), tap "Find Trades".
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
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
    "Active setup (Creation & friends)": PRESETS_DIR / "creation_inventory.json",
    "Archived setup (Green Lightning & friends)": PRESETS_DIR / "green_lightning_inventory.json",
}
GOALS_PRESETS = {
    "Active setup (Creation & friends)": PRESETS_DIR / "creation_goals.json",
    "Archived setup (Green Lightning & friends)": PRESETS_DIR / "green_lightning_goals.json",
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
else:
    show_any = st.checkbox("Just show me anything I can trade for (skip the filters below)", value=False)
    min_profit_millions = st.slider("Minimum profit (in millions of value)", 0, 200, 0, step=5)
    any_fair = st.checkbox("Also include break-even trades (no loss, no big gain)", value=True)
    min_demand = st.slider("Minimum demand of what you'd receive (0 = don't care, 10 = very tradeable)", 0, 10, 0)
    want_names = st.multiselect("Only show trades that give me one of these (optional)", _catalog_names())

    goals = Goals(
        any=show_any,
        min_profit=min_profit_millions * 1_000_000 if min_profit_millions > 0 else None,
        any_fair=any_fair,
        min_demand=min_demand if min_demand > 0 else None,
        want_item=want_names or None,
        limit=1000,
    )

# ------------------------------------------------------------------- action
find_clicked = st.button("🔎 Find Trades", type="primary", use_container_width=True)

if find_clicked:
    if not inventory.items:
        st.warning("Add at least one item you own first.")
        st.stop()

    gamersberg = GamersbergSource()
    bfv = BloxFruitsValuesSource()
    try:
        with st.spinner("Scanning live trade feeds... this can take a couple of minutes."):
            item_names = [entry.name for entry in inventory.items]
            with ThreadPoolExecutor(max_workers=2) as executor:
                f_gamersberg_raw = executor.submit(gamersberg.fetch_listings_raw, fresh=False)
                f_bfv_raw = executor.submit(bfv.fetch_listings_raw, item_names=item_names, fresh=False)
                catalog = gamersberg.fetch_catalog(fresh=False)
                gamersberg_raw = f_gamersberg_raw.result()
                bfv_raw = f_bfv_raw.result()

            listings = build_listings(gamersberg_raw, catalog) + build_listings_bfv(bfv_raw, catalog)
            inv_counts = inventory_counts(inventory)
            matches = find_matches(listings, inv_counts, goals)
    finally:
        gamersberg.close()
        bfv.close()

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
                "Poster": m.listing.poster_name,
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
