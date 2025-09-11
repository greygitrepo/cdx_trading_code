"""Replay OB-Flow with stub LOB and TradeState to evaluate behavior offline.

Consumes data/stubs/ws/orderbook1_<SYMBOL>.jsonl via PublicWS in STUB mode.
Outputs JSONL events under logs/replay_obflow and a JSON summary in reports/.
"""
from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path

# Ensure project root is importable when run directly
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot.app.runners.replay_runner import ReplayRunner, ReplayConfig  # noqa: E402


def run(symbol: str, max_sec: float, qty_usdt: float, out_path: str | None = None) -> dict:
    cfg = ReplayConfig(symbol=symbol, max_sec=max_sec, qty_usdt=qty_usdt, out_path=Path(out_path) if out_path else None)
    return ReplayRunner(cfg).run()


def main() -> None:
    ap = ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--max-sec", type=float, default=60.0)
    ap.add_argument("--qty-usdt", type=float, default=50.0)
    ap.add_argument("--out", default=None, help="Optional events.jsonl output path")
    args = ap.parse_args()
    summary = run(args.symbol.upper(), max_sec=args.max_sec, qty_usdt=args.qty_usdt, out_path=args.out)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
