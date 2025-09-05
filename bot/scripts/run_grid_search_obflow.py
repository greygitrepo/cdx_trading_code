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
import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

# Ensure repo root on sys.path for direct execution
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot.core.book import L2Book, apply_delta, apply_snapshot  # noqa: E402
from bot.core.data_ws import PublicWS  # noqa: E402
from bot.core.features import basic_snapshot  # noqa: E402
from bot.core.signals.obflow import OBFlowConfig, decide  # noqa: E402


def _fee_aware_targets(
    entry_price: float,
    *,
    side_long: bool,
    tp_net: float,
    sl_net: float,
    entry_fee_bps: float,
    exit_fee_bps: float,
) -> Tuple[float, float]:
    fe = max(0.0, float(entry_fee_bps)) / 1e4
    fx = max(0.0, float(exit_fee_bps)) / 1e4
    fee_sum = fe + fx
    tp_gross = max(0.0, tp_net + fee_sum)
    sl_gross = max(0.0, sl_net - fee_sum)
    if side_long:
        return entry_price * (1 + tp_gross), entry_price * (1 - sl_gross)
    return entry_price * (1 - tp_gross), entry_price * (1 + sl_gross)


def _hour_bin(ts_ms: int) -> int:
    try:
        return int((ts_ms // 1000) % 86400 // 3600)
    except Exception:
        return 0


@dataclass
class GSParams:
    tp_pct: float
    sl_pct: float
    cooldown_sec: int
    assume_entry: str  # auto|maker|taker
    assume_exit: str  # maker|taker
    obflow: OBFlowConfig
    maker_fee_bps: float
    taker_fee_bps: float


@dataclass
class GSResult:
    symbol: str
    hour: int
    tp_bps: float
    sl_bps: float
    trades: int
    wins: int
    pnl: float


def _run_single(symbol: str, p: GSParams) -> List[GSResult]:
    ws = PublicWS(symbol=symbol, depth=1)
    book = L2Book(symbol=symbol)
    pos_side: Optional[str] = None
    entry_px = 0.0
    entry_ts = 0
    tp_abs = 0.0
    sl_abs = 0.0
    last_entry_ts = -10**9
    results: dict[int, dict[str, float]] = {}

    def _add(hour: int, win: bool, pnl: float) -> None:
        rec = results.setdefault(hour, {"trades": 0, "wins": 0, "pnl": 0.0})
        rec["trades"] += 1
        if win:
            rec["wins"] += 1
        rec["pnl"] += pnl

    for ev in ws.orderbook_stream():
        etype = ev.get("type")
        if etype == "snapshot":
            apply_snapshot(
                book,
                int(ev.get("seq", 0)),
                int(ev.get("ts", 0)),
                ((float(p_), float(s_)) for p_, s_ in ev.get("bids", [])),
                ((float(p_), float(s_)) for p_, s_ in ev.get("asks", [])),
            )
        elif etype == "delta":
            ok = apply_delta(
                book,
                int(ev.get("seq", 0)),
                int(ev.get("ts", 0)),
                ((float(p_), float(s_)) for p_, s_ in ev.get("bids", [])),
                ((float(p_), float(s_)) for p_, s_ in ev.get("asks", [])),
            )
            if not ok:
                continue
        else:
            continue

        feat = basic_snapshot(book)
        ts = int(ev.get("ts") or 0)
        px = float(feat.get("micro") or feat.get("mid") or 0.0)
        if px <= 0:
            continue

        # Check exits first
        if pos_side:
            if pos_side == "BUY":
                if px >= tp_abs or px <= sl_abs:
                    # Assume taker exit by default for robustness
                    exit_bps = p.taker_fee_bps if p.assume_exit != "maker" else p.maker_fee_bps
                    pnl = (px - entry_px) - (entry_px * (p.maker_fee_bps if p.assume_entry == "maker" else p.taker_fee_bps) / 1e4) - (
                        px * exit_bps / 1e4
                    )
                    _add(_hour_bin(ts), pnl >= 0, pnl)
                    pos_side = None
            else:
                if px <= tp_abs or px >= sl_abs:
                    exit_bps = p.taker_fee_bps if p.assume_exit != "maker" else p.maker_fee_bps
                    pnl = (entry_px - px) - (entry_px * (p.maker_fee_bps if p.assume_entry == "maker" else p.taker_fee_bps) / 1e4) - (
                        px * exit_bps / 1e4
                    )
                    _add(_hour_bin(ts), pnl >= 0, pnl)
                    pos_side = None
            continue

        # Cooldown gate
        if ts - last_entry_ts < p.cooldown_sec * 1000:
            continue

        sig = decide(book, p.obflow)
        if not sig:
            continue
        # Open new trade at current px (unit qty normalization)
        pos_side = str(sig["side"]).upper()
        entry_px = px
        entry_ts = ts
        last_entry_ts = ts
        fe_bps = (
            p.maker_fee_bps
            if (p.assume_entry == "maker")
            else p.taker_fee_bps if p.assume_entry == "taker" else p.taker_fee_bps
        )
        fx_bps = p.taker_fee_bps if p.assume_exit != "maker" else p.maker_fee_bps
        tp_abs, sl_abs = _fee_aware_targets(
            entry_px,
            side_long=(pos_side == "BUY"),
            tp_net=p.tp_pct,
            sl_net=p.sl_pct,
            entry_fee_bps=fe_bps,
            exit_fee_bps=fx_bps,
        )

    out: List[GSResult] = []
    for hour, rec in sorted(results.items()):
        out.append(
            GSResult(
                symbol=symbol,
                hour=hour,
                tp_bps=p.tp_pct * 1e4,
                sl_bps=p.sl_pct * 1e4,
                trades=int(rec["trades"]),
                wins=int(rec["wins"]),
                pnl=float(rec["pnl"]),
            )
        )
    return out


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
    # OB-Flow threshold presets (lightweight): conservative/balanced/aggressive
    ap.add_argument("--preset", default="balanced", choices=["conservative", "balanced", "aggressive"])
    args = ap.parse_args()

    def preset_cfg(name: str) -> OBFlowConfig:
        if name == "conservative":
            return OBFlowConfig(
                depth_imb_L5_min=0.30,
                spread_tight_mult_mid=0.0006,
                tps_min_breakout=8.0,
                c_absorption_min=0.50,
                d_wide_spread_mult_mid=0.0025,
                d_micro_dev_mult_spread=0.65,
            )
        if name == "aggressive":
            return OBFlowConfig(
                depth_imb_L5_min=0.18,
                spread_tight_mult_mid=0.0009,
                tps_min_breakout=6.0,
                c_absorption_min=0.30,
                d_wide_spread_mult_mid=0.0012,
                d_micro_dev_mult_spread=0.35,
            )
        return OBFlowConfig(
            depth_imb_L5_min=0.25,
            spread_tight_mult_mid=0.0007,
            tps_min_breakout=8.0,
            c_absorption_min=0.45,
            d_wide_spread_mult_mid=0.0020,
            d_micro_dev_mult_spread=0.60,
        )

    tp_list = [max(0.0, float(x) / 1e4) for x in str(args.tp_bps).split(",") if x.strip()]
    sl_list = [max(0.0, float(x) / 1e4) for x in str(args.sl_bps).split(",") if x.strip()]
    symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]

    maker_fee_bps = 2.0  # default; grid does not vary fees
    taker_fee_bps = 4.0

    rows: List[GSResult] = []
    for sym in symbols:
        for tp in tp_list:
            for sl in sl_list:
                params = GSParams(
                    tp_pct=tp,
                    sl_pct=sl,
                    cooldown_sec=int(args.cooldown_sec),
                    assume_entry=str(args.assume_entry),
                    assume_exit=str(args.assume_exit),
                    obflow=preset_cfg(str(args.preset)),
                    maker_fee_bps=maker_fee_bps,
                    taker_fee_bps=taker_fee_bps,
                )
                rows.extend(_run_single(sym, params))

    # Write CSV
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    ts = int(time.time())
    csv_path = reports / f"grid_obflow_{ts}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "hour", "tp_bps", "sl_bps", "trades", "wins", "pnl"])
        for r in rows:
            w.writerow([r.symbol, r.hour, r.tp_bps, r.sl_bps, r.trades, r.wins, f"{r.pnl:.6f}"])

    # Simple JSON summary: best per symbol/hour by pnl
    best: dict[str, dict[int, dict]] = {}
    for r in rows:
        cur = best.setdefault(r.symbol, {}).get(r.hour)
        if cur is None or r.pnl > cur["pnl"]:
            best.setdefault(r.symbol, {})[r.hour] = {
                "tp_bps": r.tp_bps,
                "sl_bps": r.sl_bps,
                "trades": r.trades,
                "wins": r.wins,
                "pnl": r.pnl,
            }
    (reports / f"grid_obflow_best_{ts}.json").write_text(
        json.dumps(best, ensure_ascii=False, indent=2)
    )
    print(f"CSV: {csv_path}")


if __name__ == "__main__":
    main()

