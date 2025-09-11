"""Grid search for OB-Flow parameters over stub replay."""

from __future__ import annotations
import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from bot.core.book import L2Book, apply_delta, apply_snapshot
from bot.core.data_ws import PublicWS
from bot.core.features import basic_snapshot
from bot.core.signals.obflow import OBFlowConfig, decide
from bot.core.config import load_runtime


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


class GridSearchOBFlowRunner:
    def __init__(self, symbols: list[str], tp_list: list[float], sl_list: list[float], *, cooldown_sec: int,
                 assume_entry: str, assume_exit: str, preset: str,
                 maker_fee_bps: float = 2.0, taker_fee_bps: float = 4.0,
                 qty_usdt: float = 50.0, depth: int = 1) -> None:
        self.symbols = symbols
        self.tp_list = tp_list
        self.sl_list = sl_list
        self.cooldown_sec = cooldown_sec
        self.assume_entry = assume_entry
        self.assume_exit = assume_exit
        self.preset = preset
        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps
        self.qty_usdt = float(qty_usdt)
        self.depth = int(depth)

    def _preset_cfg(self) -> OBFlowConfig:
        if self.preset == "yaml":
            # Use current YAML params to mirror live settings
            try:
                rt = load_runtime()
                return OBFlowConfig.from_params(rt.params)
            except Exception:
                pass
        if self.preset == "loose":
            return OBFlowConfig(
                depth_imb_L5_min=0.20,
                spread_tight_mult_mid=0.0009,
                tps_min_breakout=6.0,
                c_absorption_min=0.30,
                d_wide_spread_mult_mid=0.0015,
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

    def _run_single(self, symbol: str, p: GSParams) -> List[GSResult]:
        ws = PublicWS(symbol=symbol, depth=self.depth)
        book = L2Book(symbol=symbol)
        pos_side: Optional[str] = None
        entry_px = 0.0
        # entry_ts reserved for debugging; not required in current logic
        tp_abs = 0.0
        sl_abs = 0.0
        last_entry_ts = -10**9
        results: dict[int, dict[str, float]] = {}
        # For TPS gating parity with live runner, estimate tps from seq deltas
        prev_seq: Optional[int] = None
        prev_ts: Optional[int] = None

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

            if pos_side:
                if pos_side == "BUY":
                    if px >= tp_abs or px <= sl_abs:
                        exit_bps = p.taker_fee_bps if p.assume_exit != "maker" else p.maker_fee_bps
                        pnl_px = (px - entry_px) - (
                            entry_px * (p.maker_fee_bps if p.assume_entry == "maker" else p.taker_fee_bps) / 1e4
                        ) - (px * exit_bps / 1e4)
                        qty = (self.qty_usdt / entry_px) if entry_px > 0 else 0.0
                        pnl_usdt = pnl_px * qty
                        # Accumulate
                        rec = results.setdefault(_hour_bin(ts), {"trades": 0, "wins": 0, "pnl_usdt": 0.0, "sum_ret_bps": 0.0})
                        rec["trades"] += 1
                        if pnl_usdt >= 0:
                            rec["wins"] += 1
                        rec["pnl_usdt"] += pnl_usdt
                        rec["sum_ret_bps"] += ((pnl_usdt / max(1e-9, self.qty_usdt)) * 1e4)
                        pos_side = None
                else:
                    if px <= tp_abs or px >= sl_abs:
                        exit_bps = p.taker_fee_bps if p.assume_exit != "maker" else p.maker_fee_bps
                        pnl_px = (entry_px - px) - (
                            entry_px * (p.maker_fee_bps if p.assume_entry == "maker" else p.taker_fee_bps) / 1e4
                        ) - (px * exit_bps / 1e4)
                        qty = (self.qty_usdt / entry_px) if entry_px > 0 else 0.0
                        pnl_usdt = pnl_px * qty
                        rec = results.setdefault(_hour_bin(ts), {"trades": 0, "wins": 0, "pnl_usdt": 0.0, "sum_ret_bps": 0.0})
                        rec["trades"] += 1
                        if pnl_usdt >= 0:
                            rec["wins"] += 1
                        rec["pnl_usdt"] += pnl_usdt
                        rec["sum_ret_bps"] += ((pnl_usdt / max(1e-9, self.qty_usdt)) * 1e4)
                        pos_side = None
                continue

            if ts - last_entry_ts < p.cooldown_sec * 1000:
                continue

            # Inject TPS estimate for B-pattern gating (optional)
            try:
                seq = int(ev.get("seq") or 0)
                tps = None
                if prev_seq is not None and prev_ts is not None and seq >= prev_seq:
                    dseq = seq - prev_seq
                    dt = max(1, int((ts - prev_ts) / 1000))
                    tps = float(dseq) / float(dt)
                prev_seq, prev_ts = seq, ts
                if tps is not None:
                    setattr(book, "extra_features", {"tps": float(tps)})
            except Exception:
                pass

            sig = decide(book, p.obflow)
            if not sig:
                continue
            pos_side = str(sig["side"]).upper()
            entry_px = px
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
            trades_i = int(rec.get("trades", 0))
            wins_i = int(rec.get("wins", 0))
            pnl_usdt = float(rec.get("pnl_usdt", 0.0))
            sum_ret_bps = float(rec.get("sum_ret_bps", 0.0))
            # Pack as GSResult using pnl field to store pnl_usdt for backward compatibility
            out.append(
                GSResult(
                    symbol=symbol,
                    hour=hour,
                    tp_bps=p.tp_pct * 1e4,
                    sl_bps=p.sl_pct * 1e4,
                    trades=trades_i,
                    wins=wins_i,
                    pnl=pnl_usdt,
                )
            )
        return out

    def run(self) -> Path:
        rows: List[GSResult] = []
        ob_cfg = self._preset_cfg()
        for sym in self.symbols:
            for tp in self.tp_list:
                for sl in self.sl_list:
                    params = GSParams(
                        tp_pct=tp,
                        sl_pct=sl,
                        cooldown_sec=int(self.cooldown_sec),
                        assume_entry=str(self.assume_entry),
                        assume_exit=str(self.assume_exit),
                        obflow=ob_cfg,
                        maker_fee_bps=self.maker_fee_bps,
                        taker_fee_bps=self.taker_fee_bps,
                    )
                    rows.extend(self._run_single(sym, params))

        reports = Path("reports")
        reports.mkdir(exist_ok=True)
        ts = int(time.time())
        csv_path = reports / f"grid_obflow_{ts}.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            # pnl_usdt stored in pnl; recompute derived metrics on the fly by regrouping
            w.writerow(["symbol", "hour", "tp_bps", "sl_bps", "trades", "wins", "win_rate", "pnl_usdt", "avg_pnl_usdt", "avg_pnl_bps"])
            # Aggregate by (symbol,hour,tp,sl)
            from collections import defaultdict
            agg = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl_usdt": 0.0})
            for r in rows:
                key = (r.symbol, r.hour, r.tp_bps, r.sl_bps)
                a = agg[key]
                a["trades"] += r.trades
                a["wins"] += r.wins
                a["pnl_usdt"] += r.pnl
            for (sym, hr, tp_bps, sl_bps), a in sorted(agg.items()):
                trades = int(a["trades"]) or 0
                wins = int(a["wins"]) or 0
                pnl_usdt = float(a["pnl_usdt"]) or 0.0
                win_rate = (wins / trades) if trades > 0 else 0.0
                avg_usdt = (pnl_usdt / trades) if trades > 0 else 0.0
                avg_bps = ((avg_usdt / max(1e-9, self.qty_usdt)) * 1e4) if trades > 0 else 0.0
                w.writerow([sym, hr, f"{tp_bps:.1f}", f"{sl_bps:.1f}", trades, wins, f"{win_rate:.4f}", f"{pnl_usdt:.6f}", f"{avg_usdt:.6f}", f"{avg_bps:.2f}"])
        best: dict[str, dict[int, dict]] = {}
        for r in rows:
            cur = best.setdefault(r.symbol, {}).get(r.hour)
            if cur is None or r.pnl > cur["pnl_usdt"]:
                best.setdefault(r.symbol, {})[r.hour] = {
                    "tp_bps": r.tp_bps,
                    "sl_bps": r.sl_bps,
                    "trades": r.trades,
                    "wins": r.wins,
                    "pnl_usdt": r.pnl,
                    "win_rate": (r.wins / r.trades) if r.trades > 0 else 0.0,
                }
        (reports / f"grid_obflow_best_{ts}.json").write_text(
            json.dumps(best, ensure_ascii=False, indent=2)
        )
        return csv_path
