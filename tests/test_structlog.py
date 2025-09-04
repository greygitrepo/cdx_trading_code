from pathlib import Path
from bot.utils.structlog import StructLogger


def test_structlog_schema(tmp_path: Path) -> None:
    run_id = "run_test"
    run_dir = tmp_path / run_id
    slog = StructLogger(run_dir, run_id)

    # Emit a variety of events
    slog.log_signal(ts=1, symbol="BTCUSDT", scores={"mis": 0.6}, decision="MIS:BUY")
    slog.log_order(ts=2, symbol="BTCUSDT", plan={"side": "BUY", "qty": 0.01, "price": 50000.0}, result={"ok": True})
    slog.log_fill(ts=3, symbol="BTCUSDT", side="BUY", price=50010.0, qty=0.01, order_id="oid-1")
    slog.log_cancel(ts=4, symbol="BTCUSDT", order_link_id="ol-1", reason="test")
    slog.log_risk(ts=5, symbol="BTCUSDT", ok=False, reason="guard", context={"stage": "size"})
    slog.log_pnl(ts=6, symbol="BTCUSDT", realized=1.23, unrealized=0.0)

    # Validate JSONL lines
    fp = run_dir / "events.jsonl"
    assert fp.exists()
    lines = fp.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 6
    import json

    for ln in lines:
        obj = json.loads(ln)
        assert set(["ts", "run_id", "step", "symbol", "meta"]).issubset(obj.keys())

