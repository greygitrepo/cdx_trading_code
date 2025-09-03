"""HTML reporting for paper/backtest results (minimal skeleton)."""

from __future__ import annotations
from pathlib import Path
from datetime import datetime


def generate_report(path: Path, stats: dict | None = None) -> None:
    stats = stats or {}
    html = f"""
<!doctype html>
<html>
  <head>
    <meta charset='utf-8' />
    <title>Paper Report</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 2rem; }}
      .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
      .card {{ border: 1px solid #ddd; padding: 1rem; border-radius: 6px; }}
      h1 {{ margin-top: 0; }}
    </style>
  </head>
  <body>
    <h1>Paper Report</h1>
    <p>Generated: {datetime.utcnow().isoformat()}Z</p>
    <div class="grid">
      <div class="card">
        <h3>Performance</h3>
        <p>Trades: {stats.get('trades', 0)}</p>
        <p>PnL: {stats.get('pnl', 0.0):.4f}</p>
      </div>
      <div class="card">
        <h3>Drawdown</h3>
        <p>Max DD: {stats.get('max_dd', 0.0):.4f}</p>
      </div>
      <div class="card">
        <h3>Fill Quality</h3>
        <p>Avg slippage (bps): {stats.get('slip_bps', 0.0):.2f}</p>
      </div>
      <div class="card">
        <h3>Distribution</h3>
        <p>Win rate: {stats.get('win_rate', 0.0):.2%}</p>
      </div>
    </div>
  </body>
 </html>
"""
    path.write_text(html)
