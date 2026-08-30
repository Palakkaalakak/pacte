"""Tests for the one-file SETTINGS.json loader."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from blox_trade_finder.settings import _strip_comments, load_settings

SAMPLE = """\
// tutorial line
// another comment
{
  "send_alerts_to": "someone@example.com",
  "i_own": {"Kitsune": 1, "Dragon": 2},
  "hunted_fruits": ["Tiger"],
  "min_profit_millions": 5,
  "max_of_each_fruit_to_give": 1,
  "skip_community_voted_lose": true,
  "scan_every_minutes": 10,
  "digest_every_minutes": 45,
  "max_trades_per_email": 25,
  "alerts": [
    {
      "name": "Big profit",
      "email_every_minutes": 60,
      "min_profit_millions": 50,
      "min_confidence": 70
    },
    {
      "name": "Wants my Buddha",
      "email_every_minutes": 30,
      "trade_wants": ["Buddha"],
      "min_profit_percent": 10,
      "only_win_trades": true
    }
  ]
}
"""


@pytest.fixture()
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # .cache/generated lands in tmp
    return tmp_path


def test_strip_comments_keeps_json():
    data = json.loads(_strip_comments(SAMPLE))
    assert data["i_own"]["Dragon"] == 2


def test_load_settings_full(in_tmp):
    path = in_tmp / "SETTINGS.json"
    path.write_text(SAMPLE, encoding="utf-8")
    config = load_settings(path)

    # email
    assert config.email is not None
    assert config.email.provider == "formsubmit"
    assert config.email.to_addrs == ["someone@example.com"]

    # inventory + goals snapshots generated and valid
    inv = json.loads(Path(config.inventory_path).read_text())
    assert {i["name"]: i["qty"] for i in inv["items"]} == {"Kitsune": 1, "Dragon": 2}
    goals = json.loads(Path(config.goals_path).read_text())
    assert goals["min_profit"] == 5_000_000
    assert goals["max_qty_per_fruit"] == 1
    assert goals["exclude_lose_wfl"] is True

    # scheduling
    assert config.scan_interval_minutes == 10
    assert config.digest_interval_minutes == 45
    assert config.max_matches_per_email == 25

    # hunted fruits -> legacy instant alert_items
    assert config.alert_items == ["Tiger"]

    # alerts -> AlertRules with friendly-name mapping
    assert [r.name for r in config.rules] == ["Big profit", "Wants my Buddha"]
    big = config.rules[0]
    assert big.frequency_minutes == 60
    assert big.min_profit == 50_000_000
    assert big.min_confidence == 70
    buddha = config.rules[1]
    assert buddha.frequency_minutes == 30
    assert buddha.wants_items == ["Buddha"]
    assert buddha.min_profit_pct == pytest.approx(0.10)
    assert buddha.verdicts == ["win"]


def test_load_settings_no_email_is_dry_run(in_tmp):
    path = in_tmp / "SETTINGS.json"
    path.write_text('{"i_own": {"Kitsune": 1}}', encoding="utf-8")
    config = load_settings(path)
    assert config.email is None
    assert config.rules == []


def test_load_settings_requires_inventory(in_tmp):
    path = in_tmp / "SETTINGS.json"
    path.write_text('{"send_alerts_to": "a@b.c"}', encoding="utf-8")
    with pytest.raises(ValueError, match="i_own"):
        load_settings(path)


def test_load_settings_rejects_duplicate_alert_names(in_tmp):
    path = in_tmp / "SETTINGS.json"
    path.write_text(json.dumps({
        "i_own": {"Kitsune": 1},
        "alerts": [{"name": "dup"}, {"name": "dup"}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="same"):
        load_settings(path)


def test_repo_settings_json_is_valid():
    """The actual SETTINGS.json shipped in the repo must always load."""
    repo_settings = Path(__file__).parent.parent / "SETTINGS.json"
    cwd = os.getcwd()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            config = load_settings(repo_settings)
        finally:
            os.chdir(cwd)
    assert config.email.to_addrs == ["topical_codices_0g@icloud.com"]
    assert "Tiger" in config.alert_items
    assert len(config.rules) == 2
