import time
from datetime import datetime, timezone

from blox_trade_finder.live import LiveWorker
from blox_trade_finder.models import Goals, Inventory, InventoryEntry
from blox_trade_finder.scan import ScanResult


def test_worker_scans_repeatedly_and_stops() -> None:
    calls = []

    def fake_scan(*a, **k):
        calls.append(time.time())
        return ScanResult(matches=[], name_warnings=[], listings=[])

    w = LiveWorker(
        inventory=Inventory(items=[InventoryEntry(name="X")]), goals=Goals(any=True),
        sources=["gamersberg"], notify_cfg={}, recent_only=True, chain_cfg=None,
        interval_seconds=1, scan_fn=fake_scan,
    )
    w.start()
    time.sleep(2.5)
    snap = w.snapshot()
    w.stop()
    assert len(calls) >= 2 and snap["scans"] >= 2 and snap["error"] is None
    assert snap["view"]["count"] == 0


def test_is_scam_pct_and_abs() -> None:
    from blox_trade_finder.live import is_scam
    assert is_scam(10, 1.5, {"max_profit_pct": 1.0})
    assert not is_scam(10, 0.9, {"max_profit_pct": 1.0})
    assert is_scam(30_000_000, 0.1, {"max_profit": 20_000_000})
    assert not is_scam(30_000_000, 5.0, {})
