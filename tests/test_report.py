from pathlib import Path
from bot.scripts.make_report import compute_summary, load_events, write_html
import json


def test_compute_summary_and_html(tmp_path: Path) -> None:
    # Build synthetic events
    run_id = "run_x"
    log_dir = tmp_path / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    events = [
        {"ts": 1, "run_id": run_id, "step": "signal", "symbol": "BTCUSDT", "meta": {"decision": "BUY"}},
        {"ts": 2, "run_id": run_id, "step": "order", "symbol": "BTCUSDT", "meta": {"plan": {"price": 50000}, "result": {"ok": True}}},
        {"ts": 3, "run_id": run_id, "step": "cancel", "symbol": "BTCUSDT", "meta": {"order_link_id": "ol-1"}},
    ]
    fp = log_dir / "events.jsonl"
    with fp.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    loaded = load_events(fp)
    s = compute_summary(loaded)
    assert s["signals"] == 1
    assert s["orders"] == 1
    assert s["cancels"] == 1
    assert s["fills"] == 0  # inferred as 0 since orders == cancels

    out_fp = tmp_path / f"quick_test_{run_id}.html"
    write_html(out_fp, run_id, s)
    assert out_fp.exists() and out_fp.read_text(encoding="utf-8").strip().startswith("<html>")

