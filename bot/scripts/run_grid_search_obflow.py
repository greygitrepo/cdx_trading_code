# NOTE(grey): trivial change for push test
"""Grid-search OB-Flow parameters over stub replay to find robust ranges.

Usage examples
  python bot/scripts/run_grid_search_obflow.py \
    --symbols BTCUSDT,SOLUSDT \
    --tp-bps 10,15,20,25 \
    --sl-bps 15,20,25,30 \
    --cooldown-sec 30 \
    --assume-entry auto \
    --assume-exit taker

Outputs CSV to reports/grid_obflow_<ts>.csv and a JSON summary.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List
  
# Ensure repo root on sys.path for direct execution
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot.app.runners.grid_search_runner import GridSearchOBFlowRunner  # noqa: E402


def _default_symbols() -> List[str]:
    data_dir = Path("data/stubs/ws")
    syms: List[str] = []
    for fp in data_dir.glob("orderbook1_*.jsonl"):
        name = fp.name
        try:
            sym = name.split("orderbook1_")[1].split(".jsonl")[0]
            syms.append(sym)
        except Exception:
            continue
    return syms or ["BTCUSDT"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(_default_symbols()))
    ap.add_argument("--tp-bps", default="10,15,20,25")
    ap.add_argument("--sl-bps", default="15,20,25,30")
    ap.add_argument("--cooldown-sec", type=int, default=30)
    ap.add_argument("--assume-entry", default="auto", choices=["auto", "maker", "taker"])
    ap.add_argument("--assume-exit", default="taker", choices=["maker", "taker"])
    ap.add_argument("--preset", default="yaml", choices=["yaml", "default", "loose"])
    ap.add_argument("--qty-usdt", type=float, default=50.0)
    ap.add_argument("--depth", type=int, default=1)
    args = ap.parse_args()

    tp_list = [max(0.0, float(x) / 1e4) for x in str(args.tp_bps).split(",") if x.strip()]
    sl_list = [max(0.0, float(x) / 1e4) for x in str(args.sl_bps).split(",") if x.strip()]
    symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]

    runner = GridSearchOBFlowRunner(
        symbols=symbols,
        tp_list=tp_list,
        sl_list=sl_list,
        cooldown_sec=int(args.cooldown_sec),
        assume_entry=str(args.assume_entry),
        assume_exit=str(args.assume_exit),
        preset=str(args.preset),
        qty_usdt=float(args.qty_usdt),
        depth=int(args.depth),
    )
    csv_path = runner.run()
    print(f"CSV: {csv_path}")


if __name__ == "__main__":
    main()
