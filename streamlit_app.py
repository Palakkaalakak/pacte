"""Mobile-friendly web UI for Blox Fruits Trade Finder.

No config files, no JSON, no command line — pick a saved setup (or build your
own inventory/goals right here), tap "Find Trades".
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Always import blox_trade_finder from THIS repo's src/, never from a stale
# pip-installed copy. Streamlit Cloud caches the installed package between
# deploys, which once shipped an old run_scan() missing new keyword args.
_SRC = str(Path(__file__).parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
# Purge cached blox_trade_finder modules whenever the source on disk CHANGED (a
# redeploy updates files inside the still-running process, so old modules would
# otherwise stay in sys.modules and raise ImportError for new names). Keyed on a
# fingerprint rather than "every run", so reruns don't race with imports.
import hashlib

_fp = hashlib.sha1()
for _p in sorted(Path(_SRC).rglob("*.py")):
    try:
        _fp.update(_p.read_bytes())
    except OSError:
        pass
if getattr(sys, "_blox_src_fp", None) != _fp.hexdigest():
    for _mod in [m for m in list(sys.modules) if m.startswith("blox_trade_finder")]:
        sys.modules.pop(_mod, None)
    sys._blox_src_fp = _fp.hexdigest()

import pandas as pd
import streamlit as st

from blox_trade_finder.models import Goals, Inventory, InventoryEntry
from blox_trade_finder.live import build_arb_view, NOTIFY_MAX_AGE_MINUTES, LiveWorker, DEFAULT_BLOCKED_ITEMS, build_view, filter_chains, filter_listings
from blox_trade_finder.scan import ScanProgress, run_scan
from blox_trade_finder.sources.gamersberg import GamersbergSource
from blox_trade_finder.ui.table import format_value

PRESETS_DIR = Path(__file__).parent / "config" / "presets"
USER_INVENTORIES_DIR = Path(__file__).parent / "config" / "user_inventories"
USER_NOTIFY_DIR = Path(__file__).parent / "config" / "user_notify"
WATCHER_CONFIG_PATH = Path(__file__).parent / "config" / "watcher.json"

INVENTORY_PRESETS = {
    "Palakkaalakak's": PRESETS_DIR / "creation_inventory.json",
    "Cscgde's": PRESETS_DIR / "green_lightning_inventory.json",
}
NOTIFY_PRESETS = {
    "Palakkaalakak's": PRESETS_DIR / "creation_notify.json",
    "Cscgde's": PRESETS_DIR / "green_lightning_notify.json",
}
LIVE_SCAN_INTERVAL_SECONDS = 5 * 60
# Interactive scans page the Gamersberg feed at ~1 req/s; cap pages so a first scan
# on a fresh server finishes in ~2 minutes instead of the 24/7 watcher's full budget.
INTERACTIVE_GB_MAX_PAGES = 120
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
    "header_notify": {"en": "3. Wanted - Notify (loud sound)", "it": "3. Cercati - Notifica (suono forte)"},
    "notify_intro": {
        "en": "A loud alarm plays in your browser when a trade gives you one of these items OR gives at least the minimum profit.",
        "it": "Nel browser suona un allarme forte quando uno scambio ti dà uno di questi oggetti OPPURE ha almeno il profitto minimo.",
    },
    "notify_off": {"en": "No notifications", "it": "Nessuna notifica"},
    "notify_mode_saved": {"en": "Use a saved setup", "it": "Usa una configurazione salvata"},
    "notify_mode_mine": {"en": "My saved lists", "it": "Le mie liste salvate"},
    "notify_mode_build": {"en": "Build my own", "it": "Crea la tua"},
    "notify_saved": {"en": "Saved notify list", "it": "Lista di notifica salvata"},
    "notify_items": {"en": "Notify me when a trade gives one of these", "it": "Avvisami quando uno scambio dà uno di questi"},
    "notify_min_value": {"en": "...or when it is a profit of at least (millions, 0 = off)", "it": "...o quando il profitto è almeno (milioni, 0 = off)"},
    "notify_save_name": {"en": "Name to save this list as", "it": "Nome con cui salvare questa lista"},
    "notify_save_btn": {"en": "💾 Save notify list", "it": "💾 Salva lista di notifica"},
    "notify_saved_ok": {"en": "Saved \"{name}\"!", "it": "Salvato \"{name}\"!"},
    "notify_summary": {
        "en": "Alarm if a trade gives: {items} | or has {value}+ profit",
        "it": "Allarme se uno scambio dà: {items} | o ha {value}+ di profitto",
    },
    "notify_no_saved": {"en": "No saved notify lists yet.", "it": "Nessuna lista di notifica salvata."},
    "live_toggle": {
        "en": "🔁 Live mode: rescan every 5 minutes & sound the alarm on new hits",
        "it": "🔁 Modalità live: riscansiona ogni 5 minuti e suona l'allarme sui nuovi risultati",
    },
    "live_next": {"en": "Next automatic scan in {s}s (keep this tab open)", "it": "Prossima scansione automatica tra {s}s (tieni aperta questa scheda)"},
    "notify_test": {"en": "🔊 Test alarm sound", "it": "🔊 Prova suono allarme"},
    "notify_alert": {"en": "🚨 {n} new notify hit(s)!", "it": "🚨 {n} nuovi risultati da notificare!"},
    "col_notify": {"en": "🔔", "it": "🔔"},
    "chain_header": {"en": "🔗 Chain trades (research mode)", "it": "🔗 Scambi a catena (modalità ricerca)"},
    "chain_intro": {
        "en": "Finds sequences where each trade wants what the previous one gave (X→Y, Y→Z, Z→X…). Start from an item you own and run the steps back to back for profit or to reach an item you want. Only 1-for-1 listings are chained.",
        "it": "Trova sequenze in cui ogni scambio richiede ciò che il precedente ha dato (X→Y, Y→Z, Z→X…). Parti da un oggetto che possiedi ed esegui i passaggi di fila per profitto o per ottenere ciò che vuoi. Solo annunci 1 a 1.",
    },
    "chain_max_age": {"en": "Max age of each step (minutes)", "it": "Età massima di ogni passaggio (minuti)"},
    "chain_max_steps": {"en": "Max steps in a chain", "it": "Passaggi massimi in una catena"},
    "chain_min_profit": {"en": "Min profit (millions, 0 = any gain)", "it": "Profitto min (milioni, 0 = qualsiasi guadagno)"},
    "chain_btn": {"en": "🔗 Find Chain Trades", "it": "🔗 Trova Scambi a Catena"},
    "chain_found": {"en": "Found {n} chain(s).", "it": "Trovate {n} catene."},
    "chain_none": {
        "en": "No chains right now. Try a larger max age or more steps — chains need several fresh listings to line up.",
        "it": "Nessuna catena al momento. Prova un'età massima maggiore o più passaggi.",
    },
    "header_sources": {"en": "4. Where to look", "it": "4. Dove cercare"},
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


def _parse_millions(text: str) -> int | None:
    """'250' -> 250 (millions); suffixes k/m/b/t: '1.5b' -> 1500, '1t' -> 1,000,000.
    No upper limit. None if unparseable."""
    raw = text.strip().lower().replace(",", "").replace("_", "").replace(" ", "")
    if not raw:
        return 0
    mult = {"k": 0.001, "m": 1, "b": 1_000, "t": 1_000_000}
    scale = 1
    if raw[-1] in mult:
        scale, raw = mult[raw[-1]], raw[:-1]
    try:
        return max(0, int(round(float(raw) * scale)))
    except ValueError:
        return None


def money_input(label: str, *, key: str | None = None, value: int = 0, disabled: bool = False,
                help: str | None = None) -> int:
    """Free-typing amount in MILLIONS with k/m/b/t suffixes and no cap (1t = 1,000,000)."""
    raw = st.text_input(
        label, value=str(value), key=key, disabled=disabled,
        help=(help + " " if help else "") + "Type millions, or use k / m / b / t (e.g. 500, 2.5b, 1t).",
    )
    parsed = _parse_millions(raw)
    if parsed is None:
        st.caption(f"⚠️ \"{raw}\" isn't a number — using 0.")
        return 0
    return parsed


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


# ------------------------------------------------------------------- notify
def _list_user_notify() -> dict[str, Path]:
    if not USER_NOTIFY_DIR.exists():
        return {}
    return {p.stem.replace("_", " "): p for p in sorted(USER_NOTIFY_DIR.glob("*.json"))}


def _alarm_html(count: int) -> str:
    """Loud siren via WebAudio with an in-frame Stop button (no rerun needed,
    so it works instantly even while live mode is sleeping). Unique per call so
    the iframe re-runs it. Auto-stops after 60 s."""
    return f"""<div style="font-family:sans-serif">
<button id="stop" style="width:100%;padding:12px;font-size:18px;font-weight:bold;background:#d32f2f;color:#fff;border:0;border-radius:8px;cursor:pointer">🔇 STOP ALARM</button>
<div id="st" style="font-size:12px;margin-top:4px"></div>
</div>
<script>/* {time.time()}-{count} */
(function(){{
  var title = null, C = null, o = null, timer = null;
  try {{ title = window.parent.document.title; window.parent.document.title = "🚨 {count} TRADE HIT(S)!"; }} catch(e) {{}}
  function stop() {{
    try {{ clearInterval(timer); o && o.stop(); C && C.close(); }} catch(e) {{}}
    try {{ if (title !== null) window.parent.document.title = title; }} catch(e) {{}}
    var b = document.getElementById("stop"); b.textContent = "✅ Alarm stopped"; b.disabled = true;
  }}
  document.getElementById("stop").onclick = stop;
  try {{
    C = new (window.AudioContext || window.webkitAudioContext)();
    if (C.state === "suspended") C.resume();
    setTimeout(function() {{
      var st = document.getElementById("st");
      st.textContent = C.state === "running" ? "🔊 playing" : "⚠️ browser blocked audio (" + C.state + ") — click this page once, then use Test alarm";
    }}, 300);
    var g = C.createGain(); g.gain.value = 1.0; g.connect(C.destination);
    o = C.createOscillator(); o.type = "square"; o.connect(g); o.start();
    var hi = true;
    timer = setInterval(function() {{ o.frequency.value = (hi = !hi) ? 990 : 660; }}, 250);
    setTimeout(stop, 60000);
  }} catch(e) {{}}
}})();
</script>"""


def _play_alarm(count: int) -> None:
    import streamlit.components.v1 as components
    components.html(_alarm_html(count), height=80)


# --- stale session guard -------------------------------------------------------
# Session state outlives a redeploy; objects saved by an older version of the code
# (workers, dataclasses) then raise AttributeError on newer fields. Fingerprint the
# code and wipe every saved result/worker whenever it changes.
def _code_fingerprint() -> str:
    import hashlib
    h = hashlib.sha1()
    for path in [Path(__file__), *sorted((Path(__file__).parent / "src").rglob("*.py"))]:
        try:
            h.update(path.read_bytes())
        except OSError:
            pass
    return h.hexdigest()


if st.session_state.get("_code_fp") != _code_fingerprint():
    _old_worker = st.session_state.get("live_worker")
    try:
        if _old_worker is not None:
            _old_worker.stop()
    except Exception:
        pass
    for _k in ("live_worker", "last_view", "last_listings", "chain_view", "chain_view_ts",
               "arb_view3", "seen_listing_ids", "alarm_html", "alarm_until", "alarm_seq_played"):
        st.session_state.pop(_k, None)
    st.session_state["_code_fp"] = _code_fingerprint()

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
    min_profit_millions = money_input(t("min_profit"), disabled=show_any, key="g_min_profit")
    min_profit_pct = st.number_input(
        t("min_profit_pct"), 0, None, 0, step=5,
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
        min_get_value_millions = money_input(t("min_get_value"), disabled=show_any, key="g_min_get")
        max_give_value_millions = money_input(
            t("max_give_value"), help=t("max_give_value_help"), disabled=show_any, key="g_max_give",
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

# ------------------------------------------------------------------- notify
st.header(t("header_notify"))
st.caption(t("notify_intro"))
_nm_opts = [t("notify_off"), t("notify_mode_saved"), t("notify_mode_mine"), t("notify_mode_build")]
notify_mode = st.radio("Notify", _nm_opts, index=1, horizontal=True, label_visibility="collapsed")
notify_cfg: dict = {}
if notify_mode == t("notify_mode_saved"):
    _nc = st.selectbox(t("notify_saved"), list(NOTIFY_PRESETS.keys()))
    notify_cfg = _load_json(NOTIFY_PRESETS[_nc])
elif notify_mode == t("notify_mode_mine"):
    _mine = _list_user_notify()
    if not _mine:
        st.info(t("notify_no_saved"))
    else:
        notify_cfg = _load_json(_mine[st.selectbox(t("notify_saved"), list(_mine.keys()))])
elif notify_mode == t("notify_mode_build"):
    _n_items = st.multiselect(t("notify_items"), _catalog_names())
    _n_min = money_input(t("notify_min_value"), key="n_min_profit")
    notify_cfg = {"items": _n_items, "min_profit": _n_min * 1_000_000}
    _n_name = st.text_input(t("notify_save_name"))
    if st.button(t("notify_save_btn"), use_container_width=True) and _n_name.strip() and (_n_items or _n_min):
        USER_NOTIFY_DIR.mkdir(parents=True, exist_ok=True)
        (USER_NOTIFY_DIR / f"{_safe_filename(_n_name)}.json").write_text(
            json.dumps(notify_cfg, indent=2), encoding="utf-8"
        )
        st.success(t("notify_saved_ok", name=_n_name.strip()))
_notify_age = st.number_input(
    "Alarm only for trades posted within (minutes, 0 = any age)", min_value=0,
    value=NOTIFY_MAX_AGE_MINUTES, step=1, key="notify_age_min",
)
if notify_cfg:
    st.caption(t(
        "notify_summary",
        items=", ".join(notify_cfg.get("items", [])) or "—",
        value=format_value(notify_cfg.get("min_profit") or notify_cfg.get("min_get_value") or 0),
    ))

# --------------------------------------------------------------- scam filter
with st.expander("🛡️ Scam / fake filter"):
    st.caption(
        "Hide trades that look too good to be true. Profit % is measured against what YOU give "
        "(get ÷ give − 100%): giving a 10M item for 20M of items is +100%. Applies to the table, "
        "the live checker, its alarm and chain trades. 0 = off."
    )
    _sc_pct = st.number_input("Exclude profit above (% of what you give)", 0, None, 0, step=25, key="scam_pct")
    _sc_abs = money_input("Exclude profit above (millions)", key="scam_abs")
    _sc_blocked = st.text_input(
        "Exclude trades containing these items (uncertain / placeholder entries)",
        value=", ".join(w.title() for w in DEFAULT_BLOCKED_ITEMS), key="scam_blocked",
        help="Comma-separated item names. Trades with 'Or', 'Upgrade', 'Any'… aren't definite trades.",
    )
scam_cfg = {
    "blocked_items": [w.strip() for w in _sc_blocked.split(",") if w.strip()],
    "max_profit_pct": _sc_pct / 100 if _sc_pct else None,
    "max_profit": _sc_abs * 1_000_000 if _sc_abs else None,
}

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
st.number_input(
    "Hide trades older than (minutes, 0 = show all)", min_value=0, value=0, step=1, key="max_age_min",
)
live_mode = st.toggle(t("live_toggle"), value=False, key="live_mode")
live_interval = 60 * st.radio(
    "Scan every", [5, 2], horizontal=True, format_func=lambda m: f"{m} min", key="live_interval_min",
)
if notify_cfg and st.button(t("notify_test")):
    _play_alarm(0)
with st.expander("🛠 Debug: delayed alarm"):
    _dbg_delay = st.number_input("Play alarm after (seconds)", 1, 300, 15)
    if st.button("▶️ Start delayed alarm test"):
        _ph = st.empty()
        for _left in range(int(_dbg_delay), 0, -1):
            _ph.info(f"Alarm in {_left}s — switch to another tab now")
            time.sleep(1)
        _ph.empty()
        _play_alarm(1)

# Live checker runs in a background thread (see live.py) so manual scans and
# chain searches never interrupt it. Settings are re-synced on every rerun.
def _chain_cfg() -> dict:
    ss = st.session_state
    targets: set[str] = set()
    if goals.want_item:
        targets = {goals.want_item} if isinstance(goals.want_item, str) else set(goals.want_item)
    return dict(
        value_basis=goals.value_basis,
        max_age_minutes=ss.get("chain_max_age", 5),
        max_steps=None if ss.get("chain_unlimited") else ss.get("chain_max_steps", 3),
        min_profit=(_parse_millions(str(ss.get("chain_min_profit", "0"))) or 0) * 1_000_000,
        target_names=targets,
    )


def _arb_cfg() -> dict:
    ss = st.session_state
    return dict(
        value_basis=ss.get("arb_basis", "gamersberg"), min_pct=ss.get("arb_pct", 10) / 100,
        cross_site_only=ss.get("arb_cross", True), max_age_minutes=ss.get("arb_age", 10) or None,
        min_ratio=ss.get("arb_ratio", 1.25), only_mine=ss.get("arb_mine", True),
    )


worker: LiveWorker | None = st.session_state.get("live_worker")
if live_mode and inventory.items:
    if worker is None or not worker.alive:
        worker = LiveWorker(
            inventory=inventory, goals=goals, sources=selected_sources, notify_cfg=notify_cfg,
            max_age_minutes=st.session_state.get("max_age_min") or None, scam_cfg=scam_cfg,
            notify_age_minutes=_notify_age or None,
            chain_cfg=_chain_cfg() if st.session_state.get("chain_auto") else None,
            arb_cfg=_arb_cfg() if st.session_state.get("arb_auto") else None,
            interval_seconds=live_interval, gb_max_pages=INTERACTIVE_GB_MAX_PAGES,
        )
        worker.start()
        st.session_state["live_worker"] = worker
        st.session_state["alarm_seq_played"] = 0
    else:  # push current settings into the running checker
        worker.inventory, worker.goals, worker.sources = inventory, goals, selected_sources
        worker.notify_cfg, worker.scam_cfg = notify_cfg, scam_cfg
        worker.interval = live_interval
        worker.max_age_minutes = st.session_state.get("max_age_min") or None
        worker.notify_age_minutes = _notify_age or None
        worker.chain_cfg = _chain_cfg() if st.session_state.get("chain_auto") else None
        worker.arb_cfg = _arb_cfg() if st.session_state.get("arb_auto") else None
elif worker is not None:
    worker.stop()
    st.session_state.pop("live_worker", None)
    worker = None

# Interactive scans page the Gamersberg feed at ~1 request/second. Cap the
# page count so a first-ever scan on a fresh server (e.g. Streamlit Cloud,
# where nothing is cached yet) finishes in ~2 minutes instead of grinding
# through the full 400-page deep-scan budget the 24/7 watcher uses.

def _run_chains(listings: list) -> None:
    """Manual chain search; stored in session state, shown by the chain fragment."""
    from blox_trade_finder.core.chains import find_chains
    from blox_trade_finder.core.normalize import inventory_counts
    st.session_state["chain_view"] = filter_chains(
        find_chains(filter_listings(listings, scam_cfg), inventory_counts(inventory), **_chain_cfg()), scam_cfg
    )
    st.session_state["chain_view_ts"] = time.time()


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
        result = None
    if result is not None:
        progress.progress(100, text=t("progress_done"))
        progress.empty()
        st.session_state["last_listings"] = (time.time(), result.listings)
        view, st.session_state["seen_listing_ids"] = build_view(
            result, notify_cfg, max_age_minutes=st.session_state.get("max_age_min") or None,
            only_new=False, seen=st.session_state.get("seen_listing_ids"), scam_cfg=scam_cfg,
            notify_age_minutes=_notify_age or None,
        )
        st.session_state["last_view"] = view
        if view["new_hits"]:
            _play_alarm(view["new_hits"])

# ------------------------------------------------------------ results panels
def _render_view(view: dict) -> None:
    for w in view["warnings"]:
        st.warning(w)
    if view["new_hits"]:
        st.error(t("notify_alert", n=view["new_hits"]))
    st.success(t("found_matches", count=view["count"]))
    if view.get("too_old"):
        st.caption(f"⏱️ {view['too_old']} matching trade(s) hidden — older than the max trade age")
    if view.get("excluded"):
        st.caption(f"🛡️ {view['excluded']} suspicious/uncertain trade(s) hidden by the scam filter")
    if not view["rows"]:
        st.info(t("no_matches"))
        return
    df = pd.DataFrame([{
        t("col_notify"): r["notify"], t("col_source"): r["source"],
        t("col_you_give"): r["give"], t("col_you_get"): r["get"],
        t("col_profit"): r["delta"], t("col_profit_pct"): r["pct"],
        t("col_demand"): r["demand"], t("col_verdict"): r["verdict"],
        t("col_confidence"): r["conf"], t("col_posted"): _posted_ago(r["posted"]),
        t("col_link"): r["url"],
    } for r in view["rows"]])
    flags = [r["is_new"] for r in view["rows"]]
    st.dataframe(
        df.style.apply(
            lambda row: ["background-color: #1faa59; color: white; font-weight: bold"] * len(row)
            if flags[row.name] else [""] * len(row),
            axis=1,
        ),
        use_container_width=True, hide_index=True,
        column_config={t("col_link"): st.column_config.LinkColumn(t("col_link"))},
    )


def _live_panel() -> None:
    """Polls the background checker; the latest of {manual, live} view is shown."""
    ss = st.session_state
    snap = worker.snapshot() if worker is not None else None
    if snap is not None:
        if snap["scanning"]:
            st.caption("🔄 Live checker: scanning…")
        elif snap["last_scan_ts"]:
            left = max(0, int(worker.interval - (time.time() - snap["last_scan_ts"])))
            st.caption(f"🟢 Live checker running — scan #{snap['scans']}, next in {left}s")
        if snap["error"]:
            st.error(t("scan_failed", error=snap["error"]))
        if snap["alarm_seq"] > ss.get("alarm_seq_played", 0):
            ss["alarm_seq_played"] = snap["alarm_seq"]
            ss["alarm_html"] = _alarm_html(snap["alarm_hits"])
            ss["alarm_until"] = time.time() + 60
    # Same html every poll => the iframe is kept (not reloaded), so the siren plays on.
    if time.time() < ss.get("alarm_until", 0):
        import streamlit.components.v1 as components
        components.html(ss["alarm_html"], height=80)
    candidates = [v for v in (ss.get("last_view"), snap["view"] if snap else None) if v]
    if candidates:
        _render_view(max(candidates, key=lambda v: v["ts"]))


st.fragment(run_every=3 if worker is not None else None)(_live_panel)()

# ------------------------------------------------------------------- chains
with st.expander(t("chain_header"), expanded=False):
    st.write(t("chain_intro"))
    chain_max_age = st.number_input(t("chain_max_age"), 1, 1440, 5, key="chain_max_age")
    chain_unlimited = st.checkbox("♾️ Unlimited steps", value=False, key="chain_unlimited")
    chain_max_steps = st.slider(t("chain_max_steps"), 2, 10, 3, key="chain_max_steps", disabled=chain_unlimited)
    chain_min_profit = money_input(t("chain_min_profit"), key="chain_min_profit")
    st.checkbox(
        "🔁 Also search chains on every live scan (runs alongside the live checker)",
        value=False, key="chain_auto",
    )
    if st.button(t("chain_btn"), use_container_width=True, key="chain_btn"):
        if not inventory.items:
            st.warning(t("need_item_warning"))
        else:
            try:
                cached = (worker.snapshot()["listings"] if worker is not None else None) or st.session_state.get("last_listings")
                if cached and time.time() - cached[0] < LIVE_SCAN_INTERVAL_SECONDS:
                    _run_chains(cached[1])  # reuse the live checker's fresh fetch
                else:
                    with st.spinner(t("progress_start")):
                        _cres = run_scan(
                            inventory, Goals(any=True), sources=selected_sources, deep=True,
                            gb_max_pages=INTERACTIVE_GB_MAX_PAGES,
                        )
                    st.session_state["last_listings"] = (time.time(), _cres.listings)
                    _run_chains(_cres.listings)
            except Exception as exc:
                st.error(t("scan_failed", error=f"{type(exc).__name__}: {exc}"))
    def _chain_panel() -> None:
        ss = st.session_state
        snap = worker.snapshot() if worker is not None else None
        use_live = snap and snap["chains"] is not None and snap["chains_ts"] >= ss.get("chain_view_ts", 0)
        chains = snap["chains"] if use_live else ss.get("chain_view")
        if chains is None:
            return
        st.success(t("chain_found", n=len(chains)))
        if not chains:
            st.info(t("chain_none"))
            return
        st.dataframe(
            pd.DataFrame([{
                "Chain": " → ".join(c.items),
                "Steps": len(c.steps),
                t("col_profit"): format_value(c.profit),
                t("col_profit_pct"): f"{c.profit_pct:+.0%}",
                "Oldest step": f"{c.oldest_minutes:.0f}m",
            } for c in chains[:200]]),
            use_container_width=True, hide_index=True,
        )
        for c in chains[:25]:
            st.markdown(
                f"**{' → '.join(c.items)}** ({format_value(c.profit)}): "
                + " · ".join(f"[step {i}]({l.url})" for i, l in enumerate(c.steps, 1))
            )

    st.fragment(run_every=3 if worker is not None else None)(_chain_panel)()

# ---------------------------------------------------------------- arbitrage
with st.expander("⚖️ Arbitrage (Gamersberg vs bloxfruitsvalues)"):
    st.write(
        "Same-item arbitrage: buy item X from one listing and sell the same X to another for more "
        "(both legs valued on one common basis, ideally across the two sites). **Value gaps** lists "
        "items the two sites price differently."
    )
    arb_pct = st.number_input("Min profit % (on either site's values)", 0, None, 10, step=5, key="arb_pct")
    arb_ratio = st.number_input("Min item value ratio for the gap table (x)", 1.0, None, 1.25, step=0.05, key="arb_ratio")
    arb_age = st.number_input(
        "Max age of each listing (minutes, 0 = any)", 0, None, 10, step=1, key="arb_age",
        help="Older ads are likely already filled or the poster is offline.",
    )
    arb_cross = st.checkbox("Cross-site only (buy on one site, sell on the other)", value=True, key="arb_cross")
    arb_basis = st.selectbox("Value basis for profit", ["gamersberg", "bloxfruitsvalues"], key="arb_basis")
    arb_mine = st.checkbox("Only trades I can make with my inventory", value=True, key="arb_mine")
    st.checkbox("🔁 Also search arbitrage on every live scan (runs alongside the live checker)", value=False, key="arb_auto")
    if st.button("⚖️ Find Arbitrage", use_container_width=True, key="arb_btn"):
        if not inventory.items:
            st.warning(t("need_item_warning"))
        else:
            from blox_trade_finder.core.normalize import inventory_counts as _inv_counts
            try:
                cached = (worker.snapshot()["listings"] if worker is not None else None) or st.session_state.get("last_listings")
                if cached and time.time() - cached[0] < LIVE_SCAN_INTERVAL_SECONDS and set(selected_sources) == {"gamersberg", "bloxfruitsvalues"}:
                    _alist = cached[1]
                else:
                    with st.spinner(t("progress_start")):
                        _ares = run_scan(
                            inventory, Goals(any=True), sources=["gamersberg", "bloxfruitsvalues"],
                            deep=True, gb_max_pages=INTERACTIVE_GB_MAX_PAGES,
                        )
                    _alist = _ares.listings
                st.session_state["arb_view3"] = build_arb_view(
                    _alist, cfg=_arb_cfg(), inventory_counts=_inv_counts(inventory), scam_cfg=scam_cfg,
                )
            except Exception as exc:
                st.error(t("scan_failed", error=f"{type(exc).__name__}: {exc}"))
    def _arb_panel() -> None:
        snap = worker.snapshot() if worker is not None else None
        cands = [v for v in (st.session_state.get("arb_view3"), snap["arb"] if snap else None) if v]
        if not cands:
            return
        _arb = max(cands, key=lambda v: v["ts"])
        st.subheader(f"Arbitrage ({len(_arb['trades'])})")
        if _arb["trades"]:
            st.dataframe(
                pd.DataFrame(_arb["trades"]), use_container_width=True, hide_index=True,
                column_config={
                    "Buy link": st.column_config.LinkColumn("Buy link"),
                    "Sell link": st.column_config.LinkColumn("Sell link"),
                },
            )
        else:
            st.info("No same-item arbitrage right now.")
        st.subheader(f"Value gaps ({len(_arb['gaps'])})")
        if _arb["gaps"]:
            st.dataframe(pd.DataFrame(_arb["gaps"]), use_container_width=True, hide_index=True)
        else:
            st.info("No items with a big enough value gap in the data scanned.")

    st.fragment(run_every=3 if worker is not None else None)(_arb_panel)()

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
                r_min_profit_m = money_input(
                    t("rule_min_profit"),
                    value=int((raw_rule.get("min_profit") or 0) / 1_000_000),
                    key=f"rule_minprofit_{uid}",
                )
                r_min_get_m = money_input(
                    t("rule_min_get_value"),
                    value=int((raw_rule.get("min_get_value") or 0) / 1_000_000),
                    key=f"rule_minget_{uid}",
                )
            with col_p2:
                r_min_pct = st.number_input(
                    t("rule_min_profit_pct"), min_value=0,
                    value=int(round((raw_rule.get("min_profit_pct") or 0) * 100)),
                    step=5, key=f"rule_minpct_{uid}",
                )
                r_max_give_m = money_input(
                    t("rule_max_give_value"),
                    value=int((raw_rule.get("max_give_value") or 0) / 1_000_000),
                    key=f"rule_maxgive_{uid}",
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
