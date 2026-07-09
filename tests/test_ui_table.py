from datetime import datetime, timedelta, timezone
from pathlib import Path

from blox_trade_finder.core.matcher import find_matches
from blox_trade_finder.core.normalize import build_listings
from blox_trade_finder.models import Catalog, Goals
from blox_trade_finder.ui.table import format_age, write_matches_to_file


def test_write_matches_to_file_creates_file_with_match_content(
    tmp_path: Path, sample_catalog: Catalog, sample_trades_raw: list[dict]
) -> None:
    listings = build_listings(sample_trades_raw, sample_catalog)
    from collections import Counter

    matches = find_matches(listings, Counter({"shadow": 1}), Goals(any_fair=True))
    out_path = tmp_path / "results.txt"

    write_matches_to_file(matches, out_path)

    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "Yeti" in content
    assert "gamersberg" in content


def test_write_matches_to_file_handles_no_matches(tmp_path: Path) -> None:
    out_path = tmp_path / "nested" / "results.txt"
    write_matches_to_file([], out_path)
    assert out_path.exists()
    assert "No matching trades" in out_path.read_text(encoding="utf-8")


def test_format_age_minutes() -> None:
    assert format_age(datetime.now(timezone.utc) - timedelta(minutes=5)) == "5m ago"


def test_format_age_hours() -> None:
    assert format_age(datetime.now(timezone.utc) - timedelta(hours=3)) == "3h ago"


def test_format_age_days() -> None:
    assert format_age(datetime.now(timezone.utc) - timedelta(days=2)) == "2d ago"
