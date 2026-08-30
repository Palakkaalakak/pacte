"""Tests for the alert rules engine (conditions, routing, scheduling)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import blox_trade_finder.watcher as watcher_module
from blox_trade_finder.models import CatalogItem, Listing, Match
from blox_trade_finder.rules import AlertRule, route_matches
from blox_trade_finder.watcher import RuleScheduler, WatcherConfig, effective_rules, load_config

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


def _item(name: str) -> CatalogItem:
    return CatalogItem(id=abs(hash(name)) % 10_000, name=name)


def _match(
    *,
    listing_id: str = "t1",
    give: list[str] | None = None,
    want: list[str] | None = None,
    give_value: int = 100,
    get_value: int = 150,
    delta: int = 50,
    profit_pct: float = 50.0,
    demand: int = 5,
    confidence: int = 80,
    verdict: str = "win",
    source: str = "gamersberg",
) -> Match:
    listing = Listing(
        id=listing_id,
        source=source,
        url="https://example.com/t",
        poster_name="tester",
        poster_rating=5.0,
        give=[_item(n) for n in (give or ["Dragon"])],
        want=[_item(n) for n in (want or ["Kitsune"])],
        wfl={"w": 1, "f": 0, "l": 0},
        created_at=NOW,
    )
    return Match(
        listing=listing,
        give_value=give_value,
        get_value=get_value,
        delta=delta,
        profit_pct=profit_pct,
        demand=demand,
        confidence=confidence,
        score=1.0,
        reasons=[],
        verdict=verdict,
    )


# ---------------------------------------------------------------- conditions

def test_no_conditions_matches_everything():
    assert AlertRule(name="all").matches(_match())


def test_disabled_rule_never_matches():
    assert not AlertRule(name="off", enabled=False).matches(_match())


def test_min_profit():
    rule = AlertRule(name="p", min_profit=100)
    assert not rule.matches(_match(delta=50))
    assert rule.matches(_match(delta=100))


def test_min_profit_pct():
    rule = AlertRule(name="p", min_profit_pct=25.0)
    assert not rule.matches(_match(profit_pct=10.0))
    assert rule.matches(_match(profit_pct=25.0))


def test_min_get_value_and_max_give_value():
    rule = AlertRule(name="v", min_get_value=200, max_give_value=100)
    assert rule.matches(_match(get_value=200, give_value=100))
    assert not rule.matches(_match(get_value=150, give_value=100))
    assert not rule.matches(_match(get_value=200, give_value=150))


def test_gives_items_with_permanent_expansion():
    rule = AlertRule(name="g", gives_items=["Dragon"])
    assert rule.matches(_match(give=["Dragon"]))
    assert rule.matches(_match(give=["Permanent Dragon"]))
    assert not rule.matches(_match(give=["Buddha"]))


def test_gives_items_exact_only_when_permanent_disabled():
    rule = AlertRule(name="g", gives_items=["Dragon"], include_permanent=False)
    assert rule.matches(_match(give=["Dragon"]))
    assert not rule.matches(_match(give=["Permanent Dragon"]))


def test_wants_items():
    rule = AlertRule(name="w", wants_items=["Kitsune"])
    assert rule.matches(_match(want=["Kitsune"]))
    assert rule.matches(_match(want=["Permanent Kitsune"]))
    assert not rule.matches(_match(want=["Leopard"]))


def test_verdict_confidence_demand():
    rule = AlertRule(name="q", verdicts=["win"], min_confidence=70, min_demand=4)
    assert rule.matches(_match(verdict="win", confidence=80, demand=5))
    assert not rule.matches(_match(verdict="fair", confidence=80, demand=5))
    assert not rule.matches(_match(verdict="win", confidence=60, demand=5))
    assert not rule.matches(_match(verdict="win", confidence=80, demand=3))


def test_sources_filter():
    rule = AlertRule(name="s", sources=["gamersberg"])
    assert rule.matches(_match(source="gamersberg"))
    assert not rule.matches(_match(source="bloxfruitsvalues"))


def test_conditions_are_anded():
    rule = AlertRule(name="and", min_profit=40, gives_items=["Dragon"])
    assert rule.matches(_match(delta=50, give=["Dragon"]))
    assert not rule.matches(_match(delta=30, give=["Dragon"]))
    assert not rule.matches(_match(delta=50, give=["Buddha"]))


# ------------------------------------------------------------------- routing

def test_route_matches_multi_claim_and_unclaimed():
    m_dragon = _match(listing_id="a", give=["Dragon"], delta=500)
    m_big = _match(listing_id="b", give=["Buddha"], delta=500)
    m_small = _match(listing_id="c", give=["Buddha"], delta=1)
    rules = [
        AlertRule(name="dragons", gives_items=["Dragon"]),
        AlertRule(name="big", min_profit=100),
    ]
    per_rule, unclaimed = route_matches([m_dragon, m_big, m_small], rules)
    assert [m.listing.id for m in per_rule["dragons"]] == ["a"]
    assert [m.listing.id for m in per_rule["big"]] == ["a", "b"]  # a claimed twice
    assert [m.listing.id for m in unclaimed] == ["c"]


def test_route_matches_ignores_disabled_rules():
    m = _match()
    rules = [AlertRule(name="off", enabled=False)]
    per_rule, unclaimed = route_matches([m], rules)
    assert "off" not in per_rule
    assert unclaimed == [m]


# ---------------------------------------------------------- config plumbing

def test_effective_rules_converts_legacy_alert_items():
    config = WatcherConfig(alert_items=["Dragon"], rules=[AlertRule(name="mine")])
    rules = effective_rules(config)
    assert [r.name for r in rules] == ["mine", "Hunted fruits (legacy alert_items)"]
    legacy = rules[-1]
    assert legacy.frequency_minutes == 0
    assert legacy.gives_items == ["Dragon"]


def test_effective_rules_without_alert_items():
    config = WatcherConfig(rules=[AlertRule(name="only")])
    assert [r.name for r in effective_rules(config)] == ["only"]


def test_load_config_rejects_duplicate_rule_names(tmp_path):
    path = tmp_path / "watcher.json"
    path.write_text(json.dumps({"rules": [{"name": "dup"}, {"name": "dup"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate rule name"):
        load_config(path)


# ---------------------------------------------------------------- scheduler

@pytest.fixture()
def rule_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher_module, "RULE_STATE_DIR", tmp_path / "rule_state")
    return tmp_path / "rule_state"


def test_scheduler_instant_rule_delivers_immediately(rule_state_dir):
    rule = AlertRule(name="instant", frequency_minutes=0)
    scheduler = RuleScheduler([rule])
    sent: list[tuple[str, list[Match]]] = []
    m1, m2 = _match(listing_id="a", delta=10), _match(listing_id="b", delta=99)
    scheduler.dispatch({"instant": [m1, m2]}, lambda s, h: sent.append((s, h)))
    assert len(sent) == 1
    subject, hits = sent[0]
    assert "[instant]" in subject and "2" in subject
    assert [m.listing.id for m in hits] == ["b", "a"]  # sorted by -delta


def test_scheduler_instant_rule_skips_empty(rule_state_dir):
    scheduler = RuleScheduler([AlertRule(name="instant")])
    sent = []
    scheduler.dispatch({"instant": []}, lambda s, h: sent.append(s))
    assert sent == []


def test_scheduler_batched_rule_queues_then_flushes(rule_state_dir):
    rule = AlertRule(name="batched", frequency_minutes=30)
    scheduler = RuleScheduler([rule])
    sent: list[tuple[str, list[Match]]] = []

    # First dispatch: queues but does not send (clock just started).
    scheduler.dispatch({"batched": [_match(listing_id="a")]}, lambda s, h: sent.append((s, h)))
    assert sent == []

    # Rewind the persisted clock 31 minutes → a NEW scheduler (like a fresh
    # --once process) must flush the queue.
    state = scheduler._states["batched"]
    assert state.last_digest_at is not None
    state.last_digest_at -= timedelta(minutes=31)
    state.save()

    scheduler2 = RuleScheduler([rule])
    scheduler2.dispatch({"batched": [_match(listing_id="b")]}, lambda s, h: sent.append((s, h)))
    assert len(sent) == 1
    subject, hits = sent[0]
    assert "[batched]" in subject
    assert sorted(m.listing.id for m in hits) == ["a", "b"]

    # Queue is cleared afterwards.
    assert scheduler2._states["batched"].queue == []
