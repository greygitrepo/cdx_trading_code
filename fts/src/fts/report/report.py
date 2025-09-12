from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None

from .ledger import TradeRecord


def write_report(records: Iterable[TradeRecord], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "ledger.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["side", "entry", "pnl"])
        for r in records:
            writer.writerow([r.side, r.entry, r.pnl])
    if records and plt:
        fig, ax = plt.subplots()
        cum = 0
        pnl_series = []
        for r in records:
            cum += r.pnl
            pnl_series.append(cum)
        ax.plot(pnl_series)
        fig.savefig(out_dir / "pnl.png")
        plt.close(fig)
