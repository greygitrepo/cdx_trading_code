from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_events(fp: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    if not fp.exists():
        return events
    with fp.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def compute_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    signals = [e for e in events if e.get("step") == "signal" and e.get("meta", {}).get("decision")]
    orders = [e for e in events if e.get("step") == "order" and e.get("meta", {}).get("result")]
    cancels = [e for e in events if e.get("step") == "cancel"]
    fills = [e for e in events if e.get("step") == "fill"]

    # Fill rate heuristic: prefers explicit fills; fallback to (orders - cancels)
    placed = len(orders)
    explicit_fills = len(fills)
    inferred_fills = max(0, placed - len(cancels))
    fill_count = explicit_fills or inferred_fills
    fill_rate = (fill_count / placed) if placed > 0 else 0.0

    # Simple slippage estimation when available
    slips: List[float] = []
    for e in fills:
        price = e.get("meta", {}).get("price")
        # Find nearest prior order plan price if any
        if price is None:
            continue
        # approximate: look back for last order
        prior = next((o for o in reversed(orders) if o.get("ts", 0) <= e.get("ts", 0)), None)
        if prior:
            plan_price = prior.get("meta", {}).get("plan", {}).get("price")
            ref = plan_price
            if ref:
                try:
                    slips.append(abs(float(price) - float(ref)) / float(ref))
                except Exception:
                    pass
    avg_slip = sum(slips) / len(slips) if slips else None

    summary = {
        "signals": len(signals),
        "orders": placed,
        "cancels": len(cancels),
        "fills": fill_count,
        "fill_rate": round(fill_rate, 4),
        "avg_slippage": (round(avg_slip, 6) if isinstance(avg_slip, float) else None),
    }
    return summary


def write_html(out_fp: Path, run_id: str, summary: Dict[str, Any]) -> None:
    out_fp.parent.mkdir(parents=True, exist_ok=True)
    html = [
        "<html><head><meta charset='utf-8'><title>Quick Test Report</title></head><body>",
        f"<h2>Quick Test Report - {run_id}</h2>",
        "<h3>Summary</h3>",
        "<table border='1' cellpadding='6' cellspacing='0'>",
    ]
    for k, v in summary.items():
        html.append(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>")
    html.extend(["</table>", "</body></html>"])
    out_fp.write_text("\n".join(html), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build quick-test HTML report from structured events")
    ap.add_argument("--run_id", required=True)
    args = ap.parse_args()

    run_id = args.run_id
    events_fp = Path("logs") / run_id / "events.jsonl"
    events = load_events(events_fp)
    summary = compute_summary(events)
    out_fp = Path("reports") / f"quick_test_{run_id}.html"
    write_html(out_fp, run_id, summary)
    print(str(out_fp))


if __name__ == "__main__":
    main()

