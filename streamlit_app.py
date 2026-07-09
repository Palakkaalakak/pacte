"""Mobile-friendly web UI for Blox Fruits Trade Finder.

No config files, no JSON, no command line — pick a preset, tap "Find Trades".
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import streamlit as st

from blox_trade_finder.core.matcher import find_matches
from blox_trade_finder.core.normalize import build_listings, build_listings_bfv, inventory_counts
from blox_trade_finder.models import Goals, Inventory
from blox_trade_finder.sources.bloxfruitsvalues import BloxFruitsValuesSource
from blox_trade_finder.sources.gamersberg import GamersbergSource
from blox_trade_finder.ui.table import format_value

CONFIG_DIR = Path(__file__).parent / "config"

INVENTORY_PRESETS = {
    "Example inventory (sample fruits)": CONFIG_DIR / "inventory.example.json",
    "Simulation inventory (test trade)": CONFIG_DIR / "simulation_inventory.json",
}
GOALS_PRESETS = {
    "Example goals (profitable trades only)": CONFIG_DIR / "goals.example.json",
    "Simulation goals (find any test trade)": CONFIG_DIR / "simulation_goals.json",
}


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


st.set_page_config(page_title="Blox Fruits Trade Finder", page_icon="🍈", layout="centered")

st.title("🍈 Blox Fruits Trade Finder")
st.write("Pick what you own and what you're looking for, then tap **Find Trades**.")

inventory_choice = st.selectbox("What you own", list(INVENTORY_PRESETS.keys()))
goals_choice = st.selectbox("What you're looking for", list(GOALS_PRESETS.keys()))

find_clicked = st.button("🔎 Find Trades", type="primary", use_container_width=True)

if find_clicked:
    inventory = Inventory.model_validate(_load_json(INVENTORY_PRESETS[inventory_choice]))
    goals = Goals.model_validate(_load_json(GOALS_PRESETS[goals_choice]))

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
        st.info("No trades matched right now. Try the other preset, or check back later — trade feeds change constantly.")
