from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional


def generate_report(out_path: Path, data: Optional[Dict[str, Any]] = None) -> None:
    """Minimal HTML report used by tests.

    Renders a simple table with a fixed title and provided key metrics.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = data or {"trades": 1, "pnl": 0.0, "max_dd": 0.0, "slip_bps": 0.0, "win_rate": 0.0}
    rows = []
    for k, v in data.items():
        rows.append(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>")
    html = (
        "<html><head><meta charset='utf-8'><title>Paper Report</title></head><body>"
        "<h2>Paper Report</h2>"
        f"<p>Trades: {data.get('trades')}</p>"
        "<table border='1' cellpadding='6' cellspacing='0'>"
        + "".join(rows)
        + "</table></body></html>"
    )
    out_path.write_text(html, encoding="utf-8")

__all__ = ["generate_report"]
