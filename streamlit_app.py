"""Mobile-friendly web UI for Blox Fruits Trade Finder.

No config files, no JSON, no command line — pick a saved setup (or build your
own inventory/goals right here), tap "Find Trades".
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Always import blox_trade_finder from THIS repo's src/, never from a stale
# pip-installed copy. Streamlit Cloud caches the installed package between
# deploys, which once shipped an old run_scan() missing new keyword args.
_SRC = str(Path(__file__).parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
for _mod in [m for m in list(sys.modules) if m.startswith("blox_trade_finder")]:
    del sys.modules[_mod]  # drop any already-imported stale copies

import pandas as pd
import streamlit as st

from blox_trade_finder.models import Goals, Inventory, InventoryEntry
from blox_trade_finder.scan import ScanProgress, run_scan
from blox_trade_finder.sources.gamersberg import GamersbergSource
from blox_trade_finder.ui.table import format_value

PRESETS_DIR = Path(__file__).parent / "config" / "presets"
USER_INVENTORIES_DIR = Path(__file__).parent / "config" / "user_inventories"
WATCHER_CONFIG_PATH = Path(__file__).parent / "config" / "watcher.json"

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
    "mode_my_saved": {"en": "My saved inventories", "it": "I miei inventari salvati"},
    "no_saved_inventories": {
        "en": "No saved inventories yet. Build one in \"Build my own\" and save it.",
        "it": "Nessun inventario salvato. Creane uno in \"Crea la tua\" e salvalo.",
    },
    "my_saved_inventory": {"en": "Your saved inventory", "it": "Il tuo inventario salvato"},
    "edit_this_inventory": {"en": "✏️ Edit this inventory", "it": "✏️ Modifica questo inventario"},
    "delete_this_inventory": {"en": "🗑️ Delete", "it": "🗑️ Elimina"},
    "deleted_inventory": {"en": "Deleted \"{name}\".", "it": "Eliminato \"{name}\"."},
    "save_inventory_name": {
        "en": "Name to save this inventory as",
        "it": "Nome con cui salvare questo inventario",
    },
    "save_inventory_btn": {"en": "💾 Save inventory", "it": "💾 Salva inventario"},
    "saved_inventory_ok": {"en": "Saved \"{name}\"!", "it": "Salvato \"{name}\"!"},
    "save_needs_name_items": {
        "en": "Pick at least one item and enter a name before saving.",
        "it": "Scegli almeno un oggetto e inserisci un nome prima di salvare.",
    },
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
    "header_sources": {"en": "3. Where to look", "it": "3. Dove cercare"},
    "sources_both": {"en": "Both sites", "it": "Entrambi i siti"},
    "sources_gb_only": {"en": "Gamersberg only", "it": "Solo Gamersberg"},
    "sources_bfv_only": {"en": "bloxfruitsvalues.com only", "it": "Solo bloxfruitsvalues.com"},
    "sources_help": {
        "en": "Gamersberg is scanned deeply (hundreds of pages, cached between runs).",
        "it": "Gamersberg viene scansionato in profondità (centinaia di pagine, con cache tra le esecuzioni).",
    },
    "progress_gb_deep": {
        "en": "Deep-scanning Gamersberg... (page {page}, {new} new trades)",
        "it": "Scansione profonda di Gamersberg... (pagina {page}, {new} nuovi scambi)",
    },
    "watcher_header": {
        "en": "📧 Automatic scanning & email alerts (watcher)",
        "it": "📧 Scansione automatica e avvisi email (watcher)",
    },
    "watcher_intro": {
        "en": "Save a watcher config here, then run `python -m blox_trade_finder.watcher --config "
        "config/watcher.json` on any always-on machine. It scans every few minutes, emails a digest "
        "on a schedule, and sends instant alerts when specific fruits appear.",
        "it": "Salva qui una configurazione del watcher, poi esegui `python -m blox_trade_finder.watcher "
        "--config config/watcher.json` su una macchina sempre accesa. Scansiona ogni pochi minuti, "
        "invia un riepilogo via email a intervalli regolari e avvisi istantanei quando compaiono "
        "frutti specifici.",
    },
    "watcher_scan_interval": {"en": "Scan every (minutes)", "it": "Scansiona ogni (minuti)"},
    "watcher_digest_interval": {
        "en": "Email digest every (minutes)",
        "it": "Riepilogo email ogni (minuti)",
    },
    "watcher_alert_items": {
        "en": "Instant email the moment a trade gives one of these",
        "it": "Email istantanea appena uno scambio offre uno di questi",
    },
    "watcher_smtp_host": {"en": "SMTP server", "it": "Server SMTP"},
    "watcher_smtp_port": {"en": "SMTP port", "it": "Porta SMTP"},
    "watcher_smtp_username": {"en": "SMTP username (your email)", "it": "Username SMTP (la tua email)"},
    "watcher_smtp_password": {
        "en": "SMTP password — Gmail: use an App Password",
        "it": "Password SMTP — Gmail: usa una App Password",
    },
    "watcher_to_addr": {"en": "Send alerts to (email)", "it": "Invia avvisi a (email)"},
    "watcher_save_btn": {"en": "💾 Save watcher config", "it": "💾 Salva configurazione watcher"},
    "watcher_saved": {
        "en": "Watcher config saved to config/watcher.json (inventory & goals snapshotted too). "
        "Run: `python -m blox_trade_finder.watcher --config config/watcher.json`",
        "it": "Configurazione salvata in config/watcher.json (anche inventario e obiettivi). "
        "Esegui: `python -m blox_trade_finder.watcher --config config/watcher.json`",
    },
    "watcher_needs_inventory": {
        "en": "Set up an inventory with at least one item first — the watcher scans with it.",
        "it": "Configura prima un inventario con almeno un oggetto — il watcher lo usa per la scansione.",
    },
    "rules_header": {
        "en": "🔔 Alert rules — what to email about & how often",
        "it": "🔔 Regole di avviso — cosa segnalare via email e ogni quanto",
    },
    "rules_intro": {
        "en": "Each rule picks WHICH trades you care about (profit, items given/asked, verdict…) "
        "and HOW OFTEN to email about them: 0 minutes = instant email, otherwise one batched "
        "email every N minutes. A trade can trigger several rules; trades no rule claims go "
        "into the regular digest.",
        "it": "Ogni regola sceglie QUALI scambi ti interessano (profitto, oggetti offerti/richiesti, "
        "verdetto…) e OGNI QUANTO inviarli via email: 0 minuti = email istantanea, altrimenti "
        "un'email raggruppata ogni N minuti. Uno scambio può attivare più regole; gli scambi non "
        "catturati da nessuna regola finiscono nel riepilogo normale.",
    },
    "rules_none": {
        "en": "No rules yet — add one below.",
        "it": "Nessuna regola — aggiungine una qui sotto.",
    },
    "rule_add_btn": {"en": "➕ Add alert rule", "it": "➕ Aggiungi regola di avviso"},
    "rule_delete_btn": {"en": "🗑️ Delete rule", "it": "🗑️ Elimina regola"},
    "rule_name": {"en": "Rule name", "it": "Nome regola"},
    "rule_enabled": {"en": "Enabled", "it": "Attiva"},
    "rule_frequency": {"en": "Email every (min)", "it": "Email ogni (min)"},
    "rule_frequency_help": {
        "en": "0 = instant email the moment a matching trade appears; N = at most one batched email every N minutes.",
        "it": "0 = email istantanea appena appare uno scambio corrispondente; N = al massimo un'email raggruppata ogni N minuti.",
    },
    "rule_zero_off": {"en": "0 = condition off", "it": "0 = condizione disattivata"},
    "rule_min_profit": {"en": "Min profit (millions)", "it": "Profitto min (milioni)"},
    "rule_min_profit_pct": {"en": "Min profit %", "it": "Profitto min %"},
    "rule_min_get_value": {"en": "Min value received (millions)", "it": "Valore min ricevuto (milioni)"},
    "rule_max_give_value": {"en": "Max value given (millions)", "it": "Valore max dato (milioni)"},
    "rule_gives_items": {
        "en": "Trade must GIVE one of these items",
        "it": "Lo scambio deve OFFRIRE uno di questi oggetti",
    },
    "rule_wants_items": {
        "en": "Trade must ASK FOR one of these items",
        "it": "Lo scambio deve RICHIEDERE uno di questi oggetti",
    },
    "rule_include_permanent": {
        "en": "Also match Permanent variants",
        "it": "Includi anche le varianti Permanent",
    },
    "rule_verdicts": {"en": "Verdict (empty = any)", "it": "Verdetto (vuoto = qualsiasi)"},
    "rule_min_confidence": {"en": "Min confidence (0=off)", "it": "Confidenza min (0=off)"},
    "rule_min_demand": {"en": "Min demand (0=off)", "it": "Domanda min (0=off)"},
    "rule_sources": {"en": "Sources (empty = any)", "it": "Fonti (vuoto = qualsiasi)"},
    "rule_name_dup": {
        "en": "Two rules have the same name — rule names must be unique.",
        "it": "Due regole hanno lo stesso nome — i nomi delle regole devono essere unici.",
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
    "scan_failed": {
        "en": "Scan failed: {error}",
        "it": "Scansione fallita: {error}",
    },
    "scan_failed_details": {
        "en": "Technical details",
        "it": "Dettagli tecnici",
    },
    "catalog_failed": {
        "en": "Could not fetch the item catalog from Gamersberg: {error}. "
              "The site may be down or blocking this server — try again in a minute.",
        "it": "Impossibile recuperare il catalogo oggetti da Gamersberg: {error}. "
              "Il sito potrebbe essere giù o bloccare questo server — riprova tra un minuto.",
    },
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


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip().replace(" ", "_")
    return cleaned or "inventory"


def _list_user_inventories() -> dict[str, Path]:
    """Map display name -> path for every saved user inventory."""
    result: dict[str, Path] = {}
    if USER_INVENTORIES_DIR.is_dir():
        for path in sorted(USER_INVENTORIES_DIR.glob("*.json")):
            try:
                data = _load_json(path)
                display = data.get("display_name") or path.stem
            except (json.JSONDecodeError, OSError):
                continue
            result[display] = path
    return result


def _save_user_inventory(name: str, inventory: Inventory) -> None:
    USER_INVENTORIES_DIR.mkdir(parents=True, exist_ok=True)
    data = inventory.model_dump()
    data["display_name"] = name
    path = USER_INVENTORIES_DIR / f"{_safe_filename(name)}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@st.cache_resource(show_spinner=False)
def _catalog_names_cached() -> list[str]:
    source = GamersbergSource()
    try:
        catalog = source.fetch_catalog(fresh=False)
    finally:
        source.close()
    return sorted(item.name for item in catalog.items)


def _catalog_names() -> list[str]:
    """Catalog names with a visible error instead of a silent blank page when
    Gamersberg is unreachable (seen on hosted runtimes like Streamlit Cloud)."""
    try:
        with st.spinner(t("progress_catalog")):
            return _catalog_names_cached()
    except Exception as exc:
        st.error(t("catalog_failed", error=f"{type(exc).__name__}: {exc}"))
        st.stop()
        raise  # unreachable — st.stop() halts the script; keeps type checkers happy


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

# Switch the mode radio to the builder BEFORE it is instantiated (Streamlit
# forbids mutating a widget's session key after creation in the same run).
if st.session_state.pop("switch_to_builder", False):
    st.session_state["inventory_mode_radio"] = t("mode_build_own")

inventory_mode = st.radio(
    "Inventory",
    [t("mode_saved"), t("mode_my_saved"), t("mode_build_own")],
    horizontal=True,
    label_visibility="collapsed",
    key="inventory_mode_radio",
)

if inventory_mode == t("mode_saved"):
    inventory_choice = st.selectbox(t("saved_inventory"), list(INVENTORY_PRESETS.keys()))
    inventory = Inventory.model_validate(_load_json(INVENTORY_PRESETS[inventory_choice]))
    with st.expander(t("see_inventory", name=inventory_choice)):
        for line in _inventory_preview_lines(inventory):
            st.write(f"- {line}")
elif inventory_mode == t("mode_my_saved"):
    user_invs = _list_user_inventories()
    if not user_invs:
        st.info(t("no_saved_inventories"))
        inventory = Inventory(items=[])
    else:
        user_choice = st.selectbox(t("my_saved_inventory"), list(user_invs.keys()))
        raw = _load_json(user_invs[user_choice])
        raw.pop("display_name", None)
        inventory = Inventory.model_validate(raw)
        with st.expander(t("see_inventory", name=user_choice)):
            for line in _inventory_preview_lines(inventory):
                st.write(f"- {line}")
        col_edit, col_delete = st.columns(2)
        with col_edit:
            if st.button(t("edit_this_inventory"), use_container_width=True):
                # Seed the builder with this inventory, then flip modes.
                st.session_state["builder_prefill_names"] = [e.name for e in inventory.items]
                for e in inventory.items:
                    st.session_state[f"qty_{e.name}"] = e.qty
                st.session_state["builder_prefill_save_name"] = user_choice
                st.session_state["switch_to_builder"] = True
                st.rerun()
        with col_delete:
            if st.button(t("delete_this_inventory"), use_container_width=True):
                user_invs[user_choice].unlink(missing_ok=True)
                st.toast(t("deleted_inventory", name=user_choice))
                st.rerun()
else:
    all_items = _catalog_names()
    prefill = st.session_state.pop("builder_prefill_names", None)
    if prefill is not None:
        st.session_state["builder_multiselect"] = [n for n in prefill if n in all_items]
    owned_names = st.multiselect(t("owned_items"), all_items, key="builder_multiselect")
    entries = []
    if owned_names:
        st.caption(t("qty_caption"))
        for name in owned_names:
            qty = st.number_input(name, min_value=1, value=1, step=1, key=f"qty_{name}")
            entries.append(InventoryEntry(name=name, qty=qty))
    inventory = Inventory(items=entries)

    col_name, col_save = st.columns([3, 1])
    with col_name:
        save_name = st.text_input(
            t("save_inventory_name"),
            value=st.session_state.pop("builder_prefill_save_name", ""),
            key="builder_save_name",
        )
    with col_save:
        st.write("")  # vertical alignment shim
        if st.button(t("save_inventory_btn"), use_container_width=True):
            if save_name.strip() and inventory.items:
                _save_user_inventory(save_name.strip(), inventory)
                st.success(t("saved_inventory_ok", name=save_name.strip()))
            else:
                st.warning(t("save_needs_name_items"))

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

# ------------------------------------------------------------------ sources
st.header(t("header_sources"))
SOURCE_CHOICES = {
    t("sources_both"): ["gamersberg", "bloxfruitsvalues"],
    t("sources_gb_only"): ["gamersberg"],
    t("sources_bfv_only"): ["bloxfruitsvalues"],
}
source_label = st.radio(
    "Sources",
    list(SOURCE_CHOICES.keys()),
    horizontal=True,
    label_visibility="collapsed",
    help=t("sources_help"),
)
selected_sources = SOURCE_CHOICES[source_label]

# ------------------------------------------------------------------- action
find_clicked = st.button(t("find_trades"), type="primary", use_container_width=True)

# Interactive scans page the Gamersberg feed at ~1 request/second. Cap the
# page count so a first-ever scan on a fresh server (e.g. Streamlit Cloud,
# where nothing is cached yet) finishes in ~2 minutes instead of grinding
# through the full 400-page deep-scan budget the 24/7 watcher uses.
INTERACTIVE_GB_MAX_PAGES = 120

if find_clicked:
    if not inventory.items:
        st.warning(t("need_item_warning"))
        st.stop()

    progress = st.progress(0, text=t("progress_start"))

    # Progress callbacks fire from run_scan's worker threads. Streamlit
    # ignores UI calls from threads without a ScriptRunContext (this is why
    # the bar used to freeze at "Fetching item catalog" on Streamlit Cloud) —
    # so capture the context here and attach it to whichever thread calls.
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        _script_ctx = get_script_run_ctx()
    except Exception:  # API moved between Streamlit versions — degrade quietly
        add_script_run_ctx = None  # type: ignore[assignment]
        _script_ctx = None

    def _safe_progress(pct: int, text: str) -> None:
        try:
            if _script_ctx is not None and add_script_run_ctx is not None:
                import threading
                add_script_run_ctx(threading.current_thread(), _script_ctx)
            progress.progress(min(max(pct, 0), 100), text=text)
        except Exception:
            # Never let a UI hiccup kill the scan itself.
            pass

    def _on_phase(phase: str) -> None:
        if phase == "catalog":
            _safe_progress(10, t("progress_catalog"))
        elif phase == "matching":
            _safe_progress(92, t("progress_matching"))

    def _on_bfv_item(name: str, done: int, total: int) -> None:
        pct = 15 + int(done / max(total, 1) * 60)
        _safe_progress(min(pct, 80), t("progress_bfv", done=done, total=total, name=name))

    def _on_gb_page(page: int, new: int) -> None:
        _safe_progress(min(15 + page // 6, 85), t("progress_gb_deep", page=page, new=new))

    try:
        result = run_scan(
            inventory,
            goals,
            sources=selected_sources,
            deep=True,
            gb_max_pages=INTERACTIVE_GB_MAX_PAGES,
            progress=ScanProgress(
                on_phase=_on_phase,
                on_bfv_item_done=_on_bfv_item,
                on_gb_page_done=_on_gb_page,
            ),
        )
    except Exception as exc:  # surface it — never leave the user staring at a frozen bar
        progress.empty()
        st.error(t("scan_failed", error=f"{type(exc).__name__}: {exc}"))
        import traceback
        with st.expander(t("scan_failed_details")):
            st.code(traceback.format_exc())
        st.stop()
    progress.progress(100, text=t("progress_done"))
    progress.empty()

    for warning in result.name_warnings:
        st.warning(warning)
    matches = result.matches

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

# ------------------------------------------------------------------ watcher
with st.expander(t("watcher_header")):
    st.write(t("watcher_intro"))

    existing_cfg: dict = {}
    if WATCHER_CONFIG_PATH.is_file():
        try:
            existing_cfg = _load_json(WATCHER_CONFIG_PATH)
        except (json.JSONDecodeError, OSError):
            existing_cfg = {}
    existing_email = existing_cfg.get("email") or {}

    col_scan, col_digest = st.columns(2)
    with col_scan:
        scan_minutes = st.number_input(
            t("watcher_scan_interval"), min_value=2, max_value=120,
            value=int(existing_cfg.get("scan_interval_minutes", 10)),
        )
    with col_digest:
        digest_minutes = st.number_input(
            t("watcher_digest_interval"), min_value=5, max_value=720,
            value=int(existing_cfg.get("digest_interval_minutes", 30)),
        )

    catalog_names = _catalog_names()
    alert_defaults = [n for n in existing_cfg.get("alert_items", []) if n in catalog_names]
    alert_items = st.multiselect(t("watcher_alert_items"), catalog_names, default=alert_defaults)

    col_host, col_port = st.columns(2)
    with col_host:
        smtp_host = st.text_input(
            t("watcher_smtp_host"), value=existing_email.get("smtp_host", "smtp.gmail.com"),
        )
    with col_port:
        smtp_port = st.number_input(
            t("watcher_smtp_port"), min_value=1, max_value=65535,
            value=int(existing_email.get("smtp_port", 587)),
        )
    col_user, col_pass = st.columns(2)
    with col_user:
        smtp_username = st.text_input(
            t("watcher_smtp_username"), value=existing_email.get("username", ""),
        )
    with col_pass:
        smtp_password = st.text_input(
            t("watcher_smtp_password"), value=existing_email.get("password", ""), type="password",
        )
    existing_to = existing_email.get("to_addrs") or [""]
    to_addr = st.text_input(t("watcher_to_addr"), value=existing_to[0])

    # ---------------------------------------------------------- alert rules
    st.subheader(t("rules_header"))
    st.caption(t("rules_intro"))

    VERDICT_CHOICES = ["win", "fair", "loss"]
    RULE_SOURCE_CHOICES = ["gamersberg", "bloxfruitsvalues"]

    if "alert_rules" not in st.session_state:
        loaded_rules = [dict(r) for r in existing_cfg.get("rules", [])]
        for i, r in enumerate(loaded_rules):
            r["_uid"] = f"loaded_{i}"
        st.session_state["alert_rules"] = loaded_rules
        st.session_state["alert_rule_seq"] = len(loaded_rules)

    if st.button(t("rule_add_btn"), use_container_width=True):
        st.session_state["alert_rule_seq"] = st.session_state.get("alert_rule_seq", 0) + 1
        seq = st.session_state["alert_rule_seq"]
        st.session_state["alert_rules"].append(
            {"name": f"Rule {seq}", "frequency_minutes": 0, "_uid": f"new_{seq}"}
        )
        st.rerun()

    if not st.session_state["alert_rules"]:
        st.info(t("rules_none"))

    edited_rules: list[dict] = []
    for idx, raw_rule in enumerate(st.session_state["alert_rules"]):
        uid = raw_rule.get("_uid") or f"idx_{idx}"
        title = raw_rule.get("name") or f"Rule {idx + 1}"
        freq = int(raw_rule.get("frequency_minutes", 0) or 0)
        badge = "⚡" if freq == 0 else f"⏱ {freq}m"
        with st.container(border=True):
            st.markdown(f"**{badge} {title}**")
            col_name, col_freq, col_on = st.columns([3, 2, 1])
            with col_name:
                r_name = st.text_input(t("rule_name"), value=title, key=f"rule_name_{uid}")
            with col_freq:
                r_freq = st.number_input(
                    t("rule_frequency"), min_value=0, max_value=1440, value=freq,
                    help=t("rule_frequency_help"), key=f"rule_freq_{uid}",
                )
            with col_on:
                r_enabled = st.checkbox(
                    t("rule_enabled"), value=bool(raw_rule.get("enabled", True)),
                    key=f"rule_on_{uid}",
                )

            st.caption(t("rule_zero_off"))
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                r_min_profit_m = st.number_input(
                    t("rule_min_profit"), min_value=0, max_value=10_000,
                    value=int((raw_rule.get("min_profit") or 0) / 1_000_000),
                    step=5, key=f"rule_minprofit_{uid}",
                )
                r_min_get_m = st.number_input(
                    t("rule_min_get_value"), min_value=0, max_value=10_000,
                    value=int((raw_rule.get("min_get_value") or 0) / 1_000_000),
                    step=5, key=f"rule_minget_{uid}",
                )
            with col_p2:
                r_min_pct = st.number_input(
                    t("rule_min_profit_pct"), min_value=0, max_value=1000,
                    value=int(round((raw_rule.get("min_profit_pct") or 0) * 100)),
                    step=5, key=f"rule_minpct_{uid}",
                )
                r_max_give_m = st.number_input(
                    t("rule_max_give_value"), min_value=0, max_value=10_000,
                    value=int((raw_rule.get("max_give_value") or 0) / 1_000_000),
                    step=5, key=f"rule_maxgive_{uid}",
                )

            r_gives = st.multiselect(
                t("rule_gives_items"), catalog_names,
                default=[n for n in raw_rule.get("gives_items", []) if n in catalog_names],
                key=f"rule_gives_{uid}",
            )
            r_wants = st.multiselect(
                t("rule_wants_items"), catalog_names,
                default=[n for n in raw_rule.get("wants_items", []) if n in catalog_names],
                key=f"rule_wants_{uid}",
            )
            r_perm = st.checkbox(
                t("rule_include_permanent"),
                value=bool(raw_rule.get("include_permanent", True)),
                key=f"rule_perm_{uid}",
            )

            col_q1, col_q2, col_q3 = st.columns(3)
            with col_q1:
                r_verdicts = st.multiselect(
                    t("rule_verdicts"), VERDICT_CHOICES,
                    default=[v for v in raw_rule.get("verdicts", []) if v in VERDICT_CHOICES],
                    key=f"rule_verdicts_{uid}",
                )
            with col_q2:
                r_min_conf = st.number_input(
                    t("rule_min_confidence"), min_value=0, max_value=100,
                    value=int(raw_rule.get("min_confidence") or 0),
                    step=5, key=f"rule_minconf_{uid}",
                )
            with col_q3:
                r_min_demand = st.number_input(
                    t("rule_min_demand"), min_value=0, max_value=10,
                    value=int(raw_rule.get("min_demand") or 0),
                    key=f"rule_mindemand_{uid}",
                )
            r_sources = st.multiselect(
                t("rule_sources"), RULE_SOURCE_CHOICES,
                default=[s for s in raw_rule.get("sources", []) if s in RULE_SOURCE_CHOICES],
                key=f"rule_sources_{uid}",
            )

            if st.button(t("rule_delete_btn"), key=f"rule_del_{uid}", use_container_width=True):
                st.session_state["alert_rules"].pop(idx)
                st.rerun()

            edited_rules.append({
                "_uid": uid,
                "name": r_name.strip() or f"Rule {idx + 1}",
                "enabled": r_enabled,
                "frequency_minutes": int(r_freq),
                "min_profit": r_min_profit_m * 1_000_000 if r_min_profit_m > 0 else None,
                "min_profit_pct": r_min_pct / 100 if r_min_pct > 0 else None,
                "min_get_value": r_min_get_m * 1_000_000 if r_min_get_m > 0 else None,
                "max_give_value": r_max_give_m * 1_000_000 if r_max_give_m > 0 else None,
                "gives_items": r_gives,
                "wants_items": r_wants,
                "include_permanent": r_perm,
                "verdicts": r_verdicts,
                "min_confidence": r_min_conf if r_min_conf > 0 else None,
                "min_demand": r_min_demand if r_min_demand > 0 else None,
                "sources": r_sources,
            })

    st.session_state["alert_rules"] = edited_rules

    rules_to_save = [{k: v for k, v in r.items() if k != "_uid"} for r in edited_rules]
    rule_names = [r["name"] for r in rules_to_save]

    if st.button(t("watcher_save_btn"), use_container_width=True):
        if not inventory.items:
            st.warning(t("watcher_needs_inventory"))
        elif len(rule_names) != len(set(rule_names)):
            st.error(t("rule_name_dup"))
        else:
            config_dir = WATCHER_CONFIG_PATH.parent
            config_dir.mkdir(parents=True, exist_ok=True)
            inv_path = config_dir / "watcher_inventory.json"
            goals_path = config_dir / "watcher_goals.json"
            with inv_path.open("w", encoding="utf-8") as f:
                json.dump(inventory.model_dump(), f, indent=2)
            with goals_path.open("w", encoding="utf-8") as f:
                json.dump(goals.model_dump(), f, indent=2)

            email_cfg = None
            if smtp_host.strip() and smtp_username.strip() and smtp_password and to_addr.strip():
                email_cfg = {
                    "smtp_host": smtp_host.strip(),
                    "smtp_port": int(smtp_port),
                    "username": smtp_username.strip(),
                    "password": smtp_password,
                    "to_addrs": [to_addr.strip()],
                }

            watcher_cfg = {
                "inventory_path": str(inv_path),
                "goals_path": str(goals_path),
                "scan_interval_minutes": int(scan_minutes),
                "digest_interval_minutes": int(digest_minutes),
                "alert_items": alert_items,
                "rules": rules_to_save,
                "sources": selected_sources,
                "email": email_cfg,
            }
            with WATCHER_CONFIG_PATH.open("w", encoding="utf-8") as f:
                json.dump(watcher_cfg, f, indent=2)
            st.success(t("watcher_saved"))
