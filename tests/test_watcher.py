from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from blox_trade_finder.emailer import EmailConfig, matches_to_html, matches_to_text
from blox_trade_finder.models import CatalogItem, Listing, Match
from blox_trade_finder.watcher import SeenTracker, WatcherConfig, _alert_names, load_config, split_alerts

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _item(name: str) -> CatalogItem:
    return CatalogItem(id=hash(name) % 10_000, name=name)


def _match(mid: str, gives: list[str], delta: int = 1_000_000) -> Match:
    listing = Listing(
        id=mid,
        source="gamersberg",
        url=f"https://example.com/{mid}",
        poster_name="tester",
        poster_rating=5.0,
        give=[_item(n) for n in gives],
        want=[_item("Buddha")],
        wfl={},
        created_at=NOW,
    )
    return Match(
        listing=listing, give_value=1_000_000, get_value=2_000_000, delta=delta,
        profit_pct=1.0, demand=7, confidence=80, score=1.0, reasons=[], verdict="win",
    )


def test_alert_names_add_permanent_variants() -> None:
    assert _alert_names(["Dragon"]) == {"dragon", "permanent dragon"}


def test_alert_names_no_double_permanent() -> None:
    assert _alert_names(["Permanent Dragon"]) == {"permanent dragon"}


def test_split_alerts_matches_give_side() -> None:
    matches = [_match("1", ["Dragon"]), _match("2", ["Buddha"]), _match("3", ["Permanent Kitsune"])]
    alerts, others = split_alerts(matches, ["Dragon", "Kitsune"])
    assert [m.listing.id for m in alerts] == ["1", "3"]
    assert [m.listing.id for m in others] == ["2"]


def test_split_alerts_empty_alert_list_sends_all_to_digest() -> None:
    matches = [_match("1", ["Dragon"])]
    alerts, others = split_alerts(matches, [])
    assert alerts == []
    assert len(others) == 1


def test_seen_tracker_persists(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    tracker = SeenTracker(path)
    m = _match("42", ["Dragon"])
    assert tracker.is_new(m)
    tracker.mark([m])
    assert not tracker.is_new(m)
    reloaded = SeenTracker(path)
    assert not reloaded.is_new(m)


def test_seen_tracker_corrupt_file_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_text("{oops", encoding="utf-8")
    tracker = SeenTracker(path)
    assert tracker.is_new(_match("1", ["Dragon"]))


def test_watcher_config_defaults(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text("{}", encoding="utf-8")
    config = load_config(path)
    assert config.scan_interval_minutes == 10
    assert config.digest_interval_minutes == 30
    assert config.sources == ["gamersberg", "bloxfruitsvalues"]
    assert config.email is None


def test_watcher_config_rejects_unknown_source(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(json.dumps({"sources": ["gamersberg", "bogus"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="bogus"):
        load_config(path)


def test_email_config_sender_falls_back_to_username() -> None:
    cfg = EmailConfig(smtp_host="smtp.test", username="me@test.com", password="x", to_addrs=["a@b.c"])
    assert cfg.sender == "me@test.com"
    cfg2 = cfg.model_copy(update={"from_addr": "other@test.com"})
    assert cfg2.sender == "other@test.com"


def test_matches_render_to_text_and_html() -> None:
    matches = [_match("1", ["Dragon"])]
    text = matches_to_text(matches, "Test digest")
    html = matches_to_html(matches, "Test digest")
    # From the user's perspective: give what the listing WANTS, get what it GIVES.
    assert "Give: Buddha -> Get: Dragon" in text
    assert "https://example.com/1" in text
    assert "<td>Dragon</td>" in html
    assert "Test digest" in html


def test_digest_state_persists_queue_across_processes(tmp_path: Path) -> None:
    from blox_trade_finder.watcher import DigestState

    path = tmp_path / "digest.json"
    state = DigestState(path)
    state.add([_match("1", ["Dragon"]), _match("2", ["Buddha"])])
    # Simulate a brand-new process (e.g. next GitHub Actions run).
    reloaded = DigestState(path)
    assert [m.listing.id for m in reloaded.queue] == ["1", "2"]


def test_digest_state_first_run_not_due_then_due_after_interval(tmp_path: Path) -> None:
    from datetime import timedelta

    from blox_trade_finder.watcher import DigestState

    path = tmp_path / "digest.json"
    state = DigestState(path)
    t0 = NOW
    assert not state.due(30, t0)  # first ever run starts the clock
    assert not state.due(30, t0 + timedelta(minutes=29))
    assert state.due(30, t0 + timedelta(minutes=31))
    state.mark_sent(t0 + timedelta(minutes=31))
    assert state.queue == []
    # After sending, the clock restarts — and survives a process restart.
    reloaded = DigestState(path)
    assert not reloaded.due(30, t0 + timedelta(minutes=40))
    assert reloaded.due(30, t0 + timedelta(minutes=62))


def test_digest_state_corrupt_file_starts_empty(tmp_path: Path) -> None:
    from blox_trade_finder.watcher import DigestState

    path = tmp_path / "digest.json"
    path.write_text("{nope", encoding="utf-8")
    state = DigestState(path)
    assert state.queue == []
    assert state.last_digest_at is None


def test_load_config_password_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from blox_trade_finder.watcher import ENV_PASSWORD_VAR

    path = tmp_path / "watcher.json"
    path.write_text(json.dumps({
        "email": {
            "smtp_host": "smtp.test", "username": "me@test.com",
            "password": "", "to_addrs": ["me@test.com"],
        }
    }), encoding="utf-8")
    monkeypatch.setenv(ENV_PASSWORD_VAR, "secret-from-env")
    config = load_config(path)
    assert config.email is not None
    assert config.email.password == "secret-from-env"


def test_load_config_empty_password_no_env_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from blox_trade_finder.watcher import ENV_PASSWORD_VAR

    monkeypatch.delenv(ENV_PASSWORD_VAR, raising=False)
    path = tmp_path / "watcher.json"
    path.write_text(json.dumps({
        "email": {
            "smtp_host": "smtp.test", "username": "me@test.com",
            "password": "", "to_addrs": ["me@test.com"],
        }
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="WATCHER_SMTP_PASSWORD"):
        load_config(path)


class TestAlreadySentDedupe:
    """_already_sent: persisted duplicate-email guard."""

    @pytest.fixture(autouse=True)
    def _isolate_log(self, tmp_path, monkeypatch):
        import blox_trade_finder.watcher as w
        monkeypatch.setattr(w, "SENT_LOG_PATH", tmp_path / "sent_log.json")

    def test_first_send_allowed_second_suppressed(self) -> None:
        from blox_trade_finder.watcher import _already_sent
        matches = [_match("t1", ["Dragon"]), _match("t2", ["Kitsune"])]
        assert _already_sent("[Big profit] 2 matching trade(s)", matches) is False
        assert _already_sent("[Big profit] 2 matching trade(s)", matches) is True

    def test_different_subject_not_suppressed(self) -> None:
        from blox_trade_finder.watcher import _already_sent
        matches = [_match("t1", ["Dragon"])]
        assert _already_sent("subject A", matches) is False
        assert _already_sent("subject B", matches) is False

    def test_different_trades_not_suppressed(self) -> None:
        from blox_trade_finder.watcher import _already_sent
        assert _already_sent("s", [_match("t1", ["Dragon"])]) is False
        assert _already_sent("s", [_match("t2", ["Dragon"])]) is False

    def test_trade_order_does_not_matter(self) -> None:
        from blox_trade_finder.watcher import _already_sent
        a, b = _match("t1", ["Dragon"]), _match("t2", ["Kitsune"])
        assert _already_sent("s", [a, b]) is False
        assert _already_sent("s", [b, a]) is True

    def test_expired_entries_allow_resend(self, monkeypatch) -> None:
        import blox_trade_finder.watcher as w
        from datetime import timedelta
        matches = [_match("t1", ["Dragon"])]
        assert w._already_sent("s", matches) is False
        # Age the recorded entry past the dedupe window.
        log = json.loads(w.SENT_LOG_PATH.read_text())
        old = datetime.now(timezone.utc) - timedelta(hours=w.SENT_DEDUPE_HOURS + 1)
        log = {k: old.isoformat() for k in log}
        w.SENT_LOG_PATH.write_text(json.dumps(log))
        assert w._already_sent("s", matches) is False

    def test_corrupt_log_recovers(self) -> None:
        import blox_trade_finder.watcher as w
        w.SENT_LOG_PATH.write_text("{corrupt")
        assert w._already_sent("s", [_match("t1", ["Dragon"])]) is False
