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

# --------------------------------------------------------------- translation
# Every user-facing string lives here, keyed the same in both languages so
# t("key") always resolves. Templates use str.format() placeholders.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "intro": {
        "en": "Set up what you own and what you want, then tap **Find Trades**.",
        "it": "Configura cosa possiedi e cosa cerchi, poi tocca **Trova Scambi**.",
    },
    "header_inventory": {"en": "1. What you own", "it": "1. Cosa possiedi"},
    "mode_saved": {"en": "Use a saved setup", "it": "Usa una configurazione salvata"},
    "mode_build_own": {"en": "Build my own", "it": "Crea la tua"},
    "mode_choose_own": {"en": "Choose my own", "it": "Scegli i tuoi obiettivi"},
    "saved_inventory": {"en": "Saved inventory", "it": "Inventario salvato"},
    "see_inventory": {"en": "See what's in \"{name}\"", "it": "Guarda cosa c'è in \"{name}\""},
    "owned_items": {"en": "Fruits/items you own", "it": "Frutti/oggetti che possiedi"},
    "qty_caption": {"en": "How many of each do you own?", "it": "Quanti ne possiedi di ciascuno?"},
    "header_goals": {"en": "2. What you're looking for", "it": "2. Cosa stai cercando"},
    "saved_goals": {"en": "Saved goals", "it": "Obiettivi salvati"},
    "see_goals": {"en": "See what \"{name}\" looks for", "it": "Guarda cosa cerca \"{name}\""},
    "show_any": {
        "en": "Just show me anything I can trade for (skip the filters below)",
        "it": "Mostrami solo qualsiasi cosa posso scambiare (salta i filtri sotto)",
    },
    "min_profit": {
        "en": "Minimum profit (in millions of value)",
        "it": "Profitto minimo (in milioni di valore)",
    },
    "min_profit_pct": {"en": "Minimum profit (%)", "it": "Profitto minimo (%)"},
    "min_profit_pct_help": {
        "en": "Trade must be worth at least this much more than what you're giving up.",
        "it": "Lo scambio deve valere almeno questo tanto in più rispetto a ciò che cedi.",
    },
    "any_fair": {
        "en": "Also include break-even trades (no loss, no big gain)",
        "it": "Includi anche scambi in pareggio (nessuna perdita, nessun grande guadagno)",
    },
    "min_demand": {
        "en": "Minimum demand of what you'd receive (0 = don't care, 10 = very tradeable)",
        "it": "Domanda minima di ciò che riceveresti (0 = non importa, 10 = molto scambiabile)",
    },
    "want_items": {
        "en": "Only show trades that give me one of these (optional)",
        "it": "Mostra solo scambi che mi danno uno di questi (opzionale)",
    },
    "want_permanent": {
        "en": "Also match the Permanent version of anything I want above",
        "it": "Includi anche la versione Permanente di ciò che voglio sopra",
    },
    "advanced_filters": {"en": "Advanced filters", "it": "Filtri avanzati"},
    "value_source": {
        "en": "Value source (which site's numbers to rank trades by)",
        "it": "Fonte dei valori (quale sito usare per classificare gli scambi)",
    },
    "min_get_value": {
        "en": "Minimum value received (in millions), regardless of profit margin",
        "it": "Valore minimo ricevuto (in milioni), indipendentemente dal margine di profitto",
    },
    "max_give_value": {
        "en": "Maximum value I'm willing to give up (in millions)",
        "it": "Valore massimo che sono disposto a cedere (in milioni)",
    },
    "max_give_value_help": {"en": "0 = no limit.", "it": "0 = nessun limite."},
    "exclude_lose_wfl": {
        "en": "Skip trades the community mostly voted a loss (Gamersberg only)",
        "it": "Salta scambi votati perlopiù come perdita dalla community (solo Gamersberg)",
    },
    "min_confidence": {
        "en": "Minimum trust score (0 = don't care)",
        "it": "Punteggio di fiducia minimo (0 = non importa)",
    },
    "min_confidence_help": {
        "en": "Blends value-source agreement, listing freshness, community votes, and whether the "
        "40% Beli-balance rule could even be checked. Raise this to filter out suspicious trades.",
        "it": "Combina l'accordo tra le fonti di valore, la freschezza dell'annuncio, i voti della "
        "community e se la regola del 40% di bilanciamento Beli era verificabile. Aumentalo per "
        "escludere scambi sospetti.",
    },
    "max_age_hours": {
        "en": "Ignore listings older than this many hours (0 = no limit)",
        "it": "Ignora annunci più vecchi di queste ore (0 = nessun limite)",
    },
    "max_qty_per_fruit": {
        "en": "Don't suggest owning more than this many of any one fruit (0 = no cap)",
        "it": "Non suggerire di possedere più di questo numero per ciascun frutto (0 = nessun limite)",
    },
    "limit": {"en": "Max results to show", "it": "Numero massimo di risultati da mostrare"},
    "see_custom_goals": {
        "en": "See what these goals look for",
        "it": "Guarda cosa cercano questi obiettivi",
    },
    "find_trades": {"en": "🔎 Find Trades", "it": "🔎 Trova Scambi"},
    "need_item_warning": {
        "en": "Add at least one item you own first.",
        "it": "Aggiungi prima almeno un oggetto che possiedi.",
    },
    "progress_start": {"en": "Starting scan...", "it": "Avvio scansione..."},
    "progress_catalog": {"en": "Fetching item catalog...", "it": "Recupero catalogo oggetti..."},
    "progress_gamersberg_bg": {
        "en": "Fetching Gamersberg trade feed in the background...",
        "it": "Recupero annunci Gamersberg in background...",
    },
    "progress_bfv": {
        "en": "Querying bloxfruitsvalues.com... ({done}/{total}: {name})",
        "it": "Interrogazione bloxfruitsvalues.com... ({done}/{total}: {name})",
    },
    "progress_wait_gamersberg": {
        "en": "Waiting for Gamersberg trade feed...",
        "it": "Attesa annunci Gamersberg...",
    },
    "progress_matching": {
        "en": "Matching trades against your goals...",
        "it": "Confronto scambi con i tuoi obiettivi...",
    },
    "progress_done": {"en": "Done!", "it": "Fatto!"},
    "found_matches": {
        "en": "Found {count} matching trade(s).",
        "it": "Trovati {count} scambi corrispondenti.",
    },
    "no_matches": {
        "en": "No trades matched right now. Try loosening your goals, or check back later — trade "
        "feeds change constantly.",
        "it": "Nessuno scambio trovato al momento. Prova ad allentare gli obiettivi, oppure "
        "ricontrolla più tardi — gli annunci cambiano di continuo.",
    },
    "col_source": {"en": "Source", "it": "Fonte"},
    "col_you_give": {"en": "You Give", "it": "Dai"},
    "col_you_get": {"en": "You Get", "it": "Ricevi"},
    "col_profit": {"en": "Profit", "it": "Profitto"},
    "col_profit_pct": {"en": "Profit %", "it": "Profitto %"},
    "col_demand": {"en": "Demand", "it": "Domanda"},
    "col_verdict": {"en": "Verdict", "it": "Verdetto"},
    "col_confidence": {"en": "Confidence", "it": "Fiducia"},
    "col_posted": {"en": "Posted", "it": "Pubblicato"},
    "col_link": {"en": "Link", "it": "Link"},
    "just_now": {"en": "just now", "it": "adesso"},
    "min_ago": {"en": "{n}m ago", "it": "{n}m fa"},
    "hours_ago": {"en": "{n}h ago", "it": "{n}h fa"},
    "days_ago": {"en": "{n}d ago", "it": "{n}g fa"},
    "preview_any": {
        "en": "Show every trade you can physically make — no filters applied.",
        "it": "Mostra ogni scambio che puoi fisicamente fare — nessun filtro applicato.",
    },
    "preview_value_source": {"en": "Value source: {source}", "it": "Fonte dei valori: {source}"},
    "preview_limit": {"en": "Showing up to {n} result(s)", "it": "Mostrando fino a {n} risultati"},
    "preview_min_profit": {"en": "Minimum profit: {value}", "it": "Profitto minimo: {value}"},
    "preview_min_profit_pct": {"en": "Minimum profit: +{pct}", "it": "Profitto minimo: +{pct}"},
    "preview_min_get_value": {
        "en": "Minimum value received: {value}",
        "it": "Valore minimo ricevuto: {value}",
    },
    "preview_max_give_value": {
        "en": "Maximum value given up: {value}",
        "it": "Valore massimo ceduto: {value}",
    },
    "preview_any_fair": {
        "en": "Also include break-even trades (no loss, no big gain)",
        "it": "Includi anche scambi in pareggio (nessuna perdita, nessun grande guadagno)",
    },
    "preview_min_demand": {
        "en": "Minimum demand of what you'd receive: {n}/10",
        "it": "Domanda minima di ciò che riceveresti: {n}/10",
    },
    "preview_want_item": {"en": "Only trades giving: {names}", "it": "Solo scambi che danno: {names}"},
    "preview_want_item_exact_suffix": {
        "en": " (exact name only, not Permanent variants)",
        "it": " (solo nome esatto, non varianti Permanenti)",
    },
    "preview_min_confidence": {
        "en": "Minimum trust score: {n}%",
        "it": "Punteggio di fiducia minimo: {n}%",
    },
    "preview_max_age_hours": {
        "en": "Ignore listings older than {n} hours",
        "it": "Ignora annunci più vecchi di {n} ore",
    },
    "preview_max_qty_per_fruit": {
        "en": "Don't suggest owning more than {n} of any one fruit",
        "it": "Non suggerire di possedere più di {n} per ciascun frutto",
    },
    "preview_exclude_lose_wfl": {
        "en": "Skip trades the community mostly voted a loss",
        "it": "Salta scambi votati perlopiù come perdita dalla community",
    },
    "preview_no_filters": {
        "en": "No extra filters — just needs to be a trade you can physically make.",
        "it": "Nessun filtro extra — deve solo essere uno scambio che puoi fisicamente fare.",
    },
}

VALUE_BASIS_LABELS = {
    "gamersberg": "Gamersberg",
    "fruityblox": "FruityBlox",
    "bloxfruit": "BloxFruit Values",
    "bloxfruitsvalues": "bloxfruitsvalues.com",
}


def t(key: str, **kwargs: object) -> str:
    template = TRANSLATIONS[key][st.session_state.get("lang", "en")]
    return template.format(**kwargs) if kwargs else template


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
        return t("just_now")
    minutes = seconds / 60
    if minutes < 60:
        return t("min_ago", n=f"{minutes:.0f}")
    hours = minutes / 60
    if hours < 24:
        return t("hours_ago", n=f"{hours:.0f}")
    days = hours / 24
    return t("days_ago", n=f"{days:.0f}")


def _inventory_preview_lines(inventory: Inventory) -> list[str]:
    return [f"{entry.name} x{entry.qty}" for entry in inventory.items]


def _goals_preview_lines(goals: Goals) -> list[str]:
    if goals.any:
        lines = [t("preview_any")]
        lines.append(t("preview_value_source", source=VALUE_BASIS_LABELS.get(goals.value_basis, goals.value_basis)))
        lines.append(t("preview_limit", n=goals.limit))
        return lines
    lines = []
    if goals.value_basis != "gamersberg":
        lines.append(t("preview_value_source", source=VALUE_BASIS_LABELS.get(goals.value_basis, goals.value_basis)))
    if goals.min_profit:
        lines.append(t("preview_min_profit", value=format_value(goals.min_profit)))
    if goals.min_profit_pct:
        lines.append(t("preview_min_profit_pct", pct=f"{goals.min_profit_pct:.0%}"))
    if goals.min_get_value:
        lines.append(t("preview_min_get_value", value=format_value(goals.min_get_value)))
    if goals.max_give_value:
        lines.append(t("preview_max_give_value", value=format_value(goals.max_give_value)))
    if goals.any_fair:
        lines.append(t("preview_any_fair"))
    if goals.min_demand:
        lines.append(t("preview_min_demand", n=goals.min_demand))
    if goals.want_item:
        names = goals.want_item if isinstance(goals.want_item, list) else [goals.want_item]
        suffix = "" if goals.want_item_include_permanent else t("preview_want_item_exact_suffix")
        lines.append(t("preview_want_item", names=", ".join(names)) + suffix)
    if goals.min_confidence:
        lines.append(t("preview_min_confidence", n=goals.min_confidence))
    if goals.max_age_hours:
        lines.append(t("preview_max_age_hours", n=f"{goals.max_age_hours:.0f}"))
    if goals.max_qty_per_fruit:
        lines.append(t("preview_max_qty_per_fruit", n=goals.max_qty_per_fruit))
    if goals.exclude_lose_wfl:
        lines.append(t("preview_exclude_lose_wfl"))
    lines.append(t("preview_limit", n=goals.limit))
    if len(lines) == 1:
        lines.insert(0, t("preview_no_filters"))
    return lines


st.set_page_config(page_title="Blox Fruits Trade Finder", page_icon="🍈", layout="centered")

# ------------------------------------------------------------------ language
col_lang, _ = st.columns([1, 3])
with col_lang:
    is_italian = st.toggle("🇬🇧 ENG / 🇮🇹 ITA", value=False)
st.session_state["lang"] = "it" if is_italian else "en"

st.title("🍈 Blox Fruits Trade Finder")
st.write(t("intro"))

# ---------------------------------------------------------------- inventory
st.header(t("header_inventory"))
inventory_mode = st.radio(
    "Inventory", [t("mode_saved"), t("mode_build_own")], horizontal=True, label_visibility="collapsed"
)

if inventory_mode == t("mode_saved"):
    inventory_choice = st.selectbox(t("saved_inventory"), list(INVENTORY_PRESETS.keys()))
    inventory = Inventory.model_validate(_load_json(INVENTORY_PRESETS[inventory_choice]))
    with st.expander(t("see_inventory", name=inventory_choice)):
        for line in _inventory_preview_lines(inventory):
            st.write(f"- {line}")
else:
    all_items = _catalog_names()
    owned_names = st.multiselect(t("owned_items"), all_items)
    entries = []
    if owned_names:
        st.caption(t("qty_caption"))
        for name in owned_names:
            qty = st.number_input(name, min_value=1, value=1, step=1, key=f"qty_{name}")
            entries.append(InventoryEntry(name=name, qty=qty))
    inventory = Inventory(items=entries)

# -------------------------------------------------------------------- goals
st.header(t("header_goals"))
goals_mode = st.radio(
    "Goals", [t("mode_saved"), t("mode_choose_own")], horizontal=True, label_visibility="collapsed"
)

if goals_mode == t("mode_saved"):
    goals_choice = st.selectbox(t("saved_goals"), list(GOALS_PRESETS.keys()))
    goals = Goals.model_validate(_load_json(GOALS_PRESETS[goals_choice]))
    with st.expander(t("see_goals", name=goals_choice)):
        for line in _goals_preview_lines(goals):
            st.write(f"- {line}")
else:
    show_any = st.checkbox(t("show_any"), value=False)
    min_profit_millions = st.slider(t("min_profit"), 0, 200, 0, step=5, disabled=show_any)
    min_profit_pct = st.slider(
        t("min_profit_pct"), 0, 200, 0, step=5,
        help=t("min_profit_pct_help"),
        disabled=show_any,
    )
    any_fair = st.checkbox(t("any_fair"), value=True, disabled=show_any)
    min_demand = st.slider(t("min_demand"), 0, 10, 0, disabled=show_any)
    want_names = st.multiselect(t("want_items"), _catalog_names(), disabled=show_any)
    want_item_include_permanent = st.checkbox(
        t("want_permanent"), value=True, disabled=show_any or not want_names,
    )

    with st.expander(t("advanced_filters")):
        value_basis_label = st.selectbox(
            t("value_source"),
            list(VALUE_BASIS_LABELS.values()),
            index=0,
            disabled=show_any,
        )
        value_basis = next(k for k, v in VALUE_BASIS_LABELS.items() if v == value_basis_label)
        min_get_value_millions = st.slider(t("min_get_value"), 0, 500, 0, step=5, disabled=show_any)
        max_give_value_millions = st.slider(
            t("max_give_value"), 0, 500, 0, step=5,
            help=t("max_give_value_help"),
            disabled=show_any,
        )
        exclude_lose_wfl = st.checkbox(t("exclude_lose_wfl"), value=False, disabled=show_any)
        min_confidence = st.slider(
            t("min_confidence"), 0, 100, 0,
            help=t("min_confidence_help"),
            disabled=show_any,
        )
        max_age_hours = st.slider(t("max_age_hours"), 0, 168, 0, disabled=show_any)
        max_qty_per_fruit = st.slider(t("max_qty_per_fruit"), 0, 20, 0, disabled=show_any)
        limit = st.slider(t("limit"), 10, 1000, 200, step=10)

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
    with st.expander(t("see_custom_goals")):
        for line in _goals_preview_lines(goals):
            st.write(f"- {line}")

# ------------------------------------------------------------------- action
find_clicked = st.button(t("find_trades"), type="primary", use_container_width=True)

if find_clicked:
    if not inventory.items:
        st.warning(t("need_item_warning"))
        st.stop()

    gamersberg = GamersbergSource()
    bfv = BloxFruitsValuesSource()
    progress = st.progress(0, text=t("progress_start"))
    try:
        item_names = [entry.name for entry in inventory.items]

        progress.progress(5, text=t("progress_catalog"))
        catalog = gamersberg.fetch_catalog(fresh=False)

        progress.progress(15, text=t("progress_gamersberg_bg"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            f_gamersberg_raw = executor.submit(gamersberg.fetch_listings_raw, fresh=False)

            bfv_raw: list[dict] = []
            if item_names:
                total = len(item_names)

                def _on_item_done(name: str, _count: list[int] = [0]) -> None:
                    _count[0] += 1
                    pct = 15 + int(_count[0] / total * 65)
                    progress.progress(min(pct, 80), text=t("progress_bfv", done=_count[0], total=total, name=name))

                bfv_raw = bfv.fetch_listings_raw(item_names=item_names, fresh=False, on_item_done=_on_item_done)

            progress.progress(85, text=t("progress_wait_gamersberg"))
            gamersberg_raw = f_gamersberg_raw.result()

        progress.progress(92, text=t("progress_matching"))
        listings = build_listings(gamersberg_raw, catalog) + build_listings_bfv(bfv_raw, catalog)
        inv_counts = inventory_counts(inventory)
        matches = find_matches(listings, inv_counts, goals)
        progress.progress(100, text=t("progress_done"))
    finally:
        gamersberg.close()
        bfv.close()
    progress.empty()

    st.success(t("found_matches", count=len(matches)))

    if matches:
        rows = []
        for m in matches:
            rows.append({
                t("col_source"): m.listing.source,
                t("col_you_give"): ", ".join(i.name for i in m.listing.want),
                t("col_you_get"): ", ".join(i.name for i in m.listing.give),
                t("col_profit"): format_value(m.delta),
                t("col_profit_pct"): f"{m.profit_pct:+.0%}",
                t("col_demand"): m.demand,
                t("col_verdict"): m.verdict.upper(),
                t("col_confidence"): f"{m.confidence}%",
                t("col_posted"): _posted_ago(m.listing.created_at),
                t("col_link"): m.listing.url,
            })
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={t("col_link"): st.column_config.LinkColumn(t("col_link"))},
        )
    else:
        st.info(t("no_matches"))
