from pathlib import Path
import json
from bot.scripts.make_report import load_events, compute_summary, write_html


def test_quick_test_flow_integration(tmp_path: Path) -> None:
    run_id = "run_it"
    # Simulate quick-test run directory and event stream
    log_dir = tmp_path / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    evs = [
        {
            "ts": 1,
            "run_id": run_id,
            "step": "signal",
            "symbol": "BTCUSDT",
            "meta": {"scores": {"mis": 0.7}, "decision": "MIS:BUY"},
        },
        {
            "ts": 2,
            "run_id": run_id,
            "step": "order",
            "symbol": "BTCUSDT",
            "meta": {"plan": {"price": 50000, "qty": 0.01}, "result": {"retCode": 0}},
        },
        {
            "ts": 3,
            "run_id": run_id,
            "step": "fill",
            "symbol": "BTCUSDT",
            "meta": {"side": "BUY", "price": 50010.0, "qty": 0.01},
        },
        {
            "ts": 4,
            "run_id": run_id,
            "step": "pnl",
            "symbol": "BTCUSDT",
            "meta": {"realized": 0.5},
        },
    ]
    fp = log_dir / "events.jsonl"
    with fp.open("w", encoding="utf-8") as f:
        for e in evs:
            f.write(json.dumps(e) + "\n")

    # Compute and write report
    loaded = load_events(fp)
    s = compute_summary(loaded)
    assert s["orders"] == 1 and s["fills"] == 1
    assert s["fill_rate"] == 1.0

    out_fp = tmp_path / f"quick_test_{run_id}.html"
    write_html(out_fp, run_id, s)
    assert out_fp.exists()
