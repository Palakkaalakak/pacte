"""Long-running watcher: scans every N minutes, emails a digest every M
minutes, and sends instant alert emails when trades give specific hunted
fruits.

Run it with:  python -m blox_trade_finder.watcher --config config/watcher.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from blox_trade_finder.cache import CACHE_DIR
from blox_trade_finder.emailer import EmailConfig, matches_to_html, matches_to_text, send_email
from blox_trade_finder.models import Goals, Inventory, Match
from blox_trade_finder.rules import AlertRule, route_matches
from blox_trade_finder.scan import VALID_SOURCES, run_scan
from blox_trade_finder.store import TradeStore

logger = logging.getLogger(__name__)

SEEN_PATH = CACHE_DIR / "watcher_seen.json"
DIGEST_STATE_PATH = CACHE_DIR / "watcher_digest_state.json"
RULE_STATE_DIR = CACHE_DIR / "watcher_rule_state"

# If set, overrides email.password from the config file — lets you commit a
# watcher config with no secret in it (e.g. for GitHub Actions, where the
# password lives in a repo secret instead).
ENV_PASSWORD_VAR = "WATCHER_SMTP_PASSWORD"


class WatcherConfig(BaseModel):
    inventory_path: str = "inventory.json"
    goals_path: str = "goals.json"
    scan_interval_minutes: int = 10
    digest_interval_minutes: int = 30
    # Instant alert the moment a matching trade GIVES one of these items
    # ("Dragon" also matches "Permanent Dragon" automatically).
    alert_items: list[str] = Field(default_factory=list)
    # Full alert rules: each has its own conditions AND its own delivery
    # frequency (see blox_trade_finder.rules.AlertRule).
    rules: list[AlertRule] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=lambda: list(VALID_SOURCES))
    send_empty_digest: bool = False
    max_matches_per_email: int = 40
    email: EmailConfig | None = None


def load_config(path: Path) -> WatcherConfig:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Env-var password override (see ENV_PASSWORD_VAR) so the config file can
    # be committed without any secret in it.
    email = data.get("email")
    if isinstance(email, dict):
        env_password = os.environ.get(ENV_PASSWORD_VAR)
        if env_password:
            email["password"] = env_password
        if not email.get("password"):
            raise ValueError(
                "email.password is empty and the "
                f"{ENV_PASSWORD_VAR} environment variable is not set — "
                "set one of them (or remove the email block for dry-run mode)"
            )

    config = WatcherConfig.model_validate(data)
    unknown = [s for s in config.sources if s not in VALID_SOURCES]
    if unknown:
        raise ValueError(f"Unknown source(s) in config: {unknown}. Valid: {list(VALID_SOURCES)}")
    names = [r.name for r in config.rules]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"Duplicate rule name(s): {dupes} — rule names must be unique")
    return config


def effective_rules(config: WatcherConfig) -> list[AlertRule]:
    """config.rules plus a legacy instant rule for `alert_items` (if set)."""
    rules = list(config.rules)
    if config.alert_items:
        rules.append(
            AlertRule(
                name="Hunted fruits (legacy alert_items)",
                frequency_minutes=0,
                gives_items=list(config.alert_items),
            )
        )
    return rules


class SeenTracker:
    """Remembers which (listing id, source) pairs we've already emailed about,
    so restarting the watcher doesn't re-alert on the same trades."""

    def __init__(self, path: Path = SEEN_PATH) -> None:
        self.path = path
        self._seen: set[str] = set()
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._seen = {str(x) for x in data}
            except (json.JSONDecodeError, OSError):
                logger.warning("seen-tracker file unreadable — starting empty")

    def _key(self, match: Match) -> str:
        return f"{match.listing.source}:{match.listing.id}"

    def is_new(self, match: Match) -> bool:
        return self._key(match) not in self._seen

    def mark(self, matches: list[Match]) -> None:
        for m in matches:
            self._seen.add(self._key(m))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(sorted(self._seen), f)


class DigestState:
    """Digest queue + last-digest wall-clock timestamp, persisted to disk so
    single-shot runs (e.g. a GitHub Actions cron firing `--once` every 10
    minutes) accumulate matches across processes and still send a digest only
    every `digest_interval_minutes`."""

    def __init__(self, path: Path = DIGEST_STATE_PATH) -> None:
        self.path = path
        self.queue: list[Match] = []
        self.last_digest_at: datetime | None = None
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                self.queue = [Match.model_validate(m) for m in data.get("queue", [])]
                raw_when = data.get("last_digest_at")
                if raw_when:
                    self.last_digest_at = datetime.fromisoformat(raw_when)
            except Exception:
                logger.warning("digest state file unreadable — starting empty")
                self.queue = []
                self.last_digest_at = None

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "queue": [m.model_dump(mode="json") for m in self.queue],
            "last_digest_at": self.last_digest_at.isoformat() if self.last_digest_at else None,
        }
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f)

    def add(self, matches: list[Match]) -> None:
        self.queue.extend(matches)
        self.save()

    def due(self, interval_minutes: int, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.last_digest_at is None:
            # First ever cycle: start the clock now rather than sending an
            # immediate (probably huge) digest.
            self.last_digest_at = now
            self.save()
            return False
        return (now - self.last_digest_at).total_seconds() >= interval_minutes * 60

    def mark_sent(self, now: datetime | None = None) -> None:
        self.queue = []
        self.last_digest_at = now or datetime.now(timezone.utc)
        self.save()


def _alert_names(alert_items: list[str]) -> set[str]:
    """Lowercased alert names, plus 'permanent X' variants."""
    names: set[str] = set()
    for name in alert_items:
        lowered = name.strip().lower()
        if not lowered:
            continue
        names.add(lowered)
        if not lowered.startswith("permanent "):
            names.add(f"permanent {lowered}")
    return names


def split_alerts(matches: list[Match], alert_items: list[str]) -> tuple[list[Match], list[Match]]:
    """(alert_matches, other_matches) — a match alerts if the trade GIVES the
    user any hunted item (including its Permanent variant)."""
    targets = _alert_names(alert_items)
    if not targets:
        return [], list(matches)
    alerts, others = [], []
    for m in matches:
        given = {item.name.lower() for item in m.listing.give}
        (alerts if given & targets else others).append(m)
    return alerts, others


def _rule_state_path(rule_name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rule_name.strip())
    return RULE_STATE_DIR / f"{safe or 'rule'}.json"


class RuleScheduler:
    """Delivers per-rule matches: instant rules email immediately; batched
    rules accumulate in a persisted per-rule DigestState and flush every
    `frequency_minutes` (works across separate --once processes too)."""

    def __init__(self, rules: list[AlertRule]) -> None:
        self.rules = [r for r in rules if r.enabled]
        self._states = {
            r.name: DigestState(_rule_state_path(r.name))
            for r in self.rules
            if r.frequency_minutes > 0
        }

    def dispatch(self, per_rule: dict[str, list[Match]], deliver) -> None:
        for rule in self.rules:
            hits = per_rule.get(rule.name, [])
            if rule.frequency_minutes <= 0:
                if hits:
                    hits = sorted(hits, key=lambda m: -m.delta)
                    deliver(f"🚨 [{rule.name}] {len(hits)} matching trade(s)!", hits)
                continue
            state = self._states[rule.name]
            if hits:
                state.add(hits)
            if state.due(rule.frequency_minutes) and state.queue:
                queued = sorted(state.queue, key=lambda m: -m.delta)
                deliver(f"[{rule.name}] {len(queued)} matching trade(s)", queued)
                state.mark_sent()


def _deliver(config: WatcherConfig, subject: str, matches: list[Match]) -> None:
    matches = matches[: config.max_matches_per_email]
    text = matches_to_text(matches, subject)
    if config.email is None:
        # Dry-run mode: no SMTP configured — print instead of send.
        print(f"\n=== [dry-run, no email config] {subject} ===")
        print(text)
        return
    try:
        send_email(config.email, subject, text, matches_to_html(matches, subject))
    except Exception:
        logger.exception("failed to send email %r — will keep running", subject)


_shutdown = False


def _request_shutdown(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    logger.info("received signal %d — finishing current cycle then stopping", signum)


def run_watcher(config: WatcherConfig, *, max_cycles: int | None = None) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _request_shutdown)
        except ValueError:
            pass  # not the main thread (e.g. under tests)

    inventory = Inventory.model_validate(json.loads(Path(config.inventory_path).read_text(encoding="utf-8")))
    goals = Goals.model_validate(json.loads(Path(config.goals_path).read_text(encoding="utf-8")))

    seen = SeenTracker()
    store = TradeStore()
    digest = DigestState()
    rules = effective_rules(config)
    scheduler = RuleScheduler(rules)
    cycles = 0

    logger.info(
        "watcher started: scan every %dm, digest every %dm, rules=%s, sources=%s, email=%s",
        config.scan_interval_minutes, config.digest_interval_minutes,
        [r.name for r in rules], config.sources, "configured" if config.email else "DRY RUN",
    )

    while not _shutdown:
        cycle_start = time.monotonic()
        try:
            result = run_scan(inventory, goals, sources=config.sources, deep=True, store=store)
            new_matches = [m for m in result.matches if seen.is_new(m)]
            logger.info(
                "cycle %d: %d matches (%d new) at %s",
                cycles + 1, len(result.matches), len(new_matches),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )

            per_rule, unclaimed = route_matches(new_matches, rules)
            scheduler.dispatch(per_rule, lambda subject, hits: _deliver(config, subject, hits))
            digest.add(unclaimed)
            seen.mark(new_matches)
        except Exception:
            logger.exception("scan cycle failed — will retry next interval")

        if digest.due(config.digest_interval_minutes):
            if digest.queue or config.send_empty_digest:
                digest.queue.sort(key=lambda m: -m.delta)
                _deliver(
                    config,
                    f"Blox Fruits digest: {len(digest.queue)} new matching trade(s)",
                    digest.queue,
                )
            digest.mark_sent()

        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break

        # Sleep in 1s slices so Ctrl-C/SIGTERM stops promptly.
        sleep_left = max(0.0, config.scan_interval_minutes * 60 - (time.monotonic() - cycle_start))
        while sleep_left > 0 and not _shutdown:
            time.sleep(min(1.0, sleep_left))
            sleep_left -= 1.0

    logger.info("watcher stopped after %d cycle(s)", cycles)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="blox-trade-watcher",
        description="Continuously scan trade feeds and email digests + instant fruit alerts.",
    )
    parser.add_argument("--config", type=Path, default=Path("config/watcher.json"))
    parser.add_argument("--once", action="store_true", help="Run a single scan cycle, then exit")
    parser.add_argument("--log-file", type=Path, default=Path("output/watcher.log"))
    args = parser.parse_args()

    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(args.log_file, encoding="utf-8"), logging.StreamHandler()],
    )

    config = load_config(args.config)
    run_watcher(config, max_cycles=1 if args.once else None)


if __name__ == "__main__":
    main()
