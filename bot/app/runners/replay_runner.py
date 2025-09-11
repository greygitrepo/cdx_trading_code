"""Replay OB-Flow runner (stub LOB, offline).

Moves the logic from `bot/scripts/run_replay_obflow.py` into a reusable class.
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bot.core.book import L2Book, apply_delta, apply_snapshot
from bot.core.config import load_runtime
from bot.core.data_ws import PublicWS
from bot.core.features import basic_snapshot
from bot.core.signals.obflow import OBFlowConfig, decide
from bot.core.execution.trade_state import Cooldown, TradeParams, TradeState


@dataclass
class ReplayConfig:
    symbol: str = "BTCUSDT"
    max_sec: float = 60.0
    qty_usdt: float = 50.0
    out_path: Optional[Path] = None


class ReplayRunner:
    def __init__(self, cfg: ReplayConfig) -> None:
        self.cfg = cfg

    def _micro(self, book: L2Book) -> float:
        feat = basic_snapshot(book)
        return float(feat.get("micro") or feat.get("mid") or 0.0)

    def run(self) -> dict:
        runtime = load_runtime()
        ob_cfg = OBFlowConfig.from_params(runtime.params)
        ws = PublicWS(symbol=self.cfg.symbol, depth=1)
        book = L2Book(symbol=self.cfg.symbol)

        cooldown = Cooldown(max_consecutive_losses=2, cooldown_sec=120)
        state: TradeState | None = None
        pos_side: str | None = None
        pos_qty: float = 0.0
        pos_entry: float = 0.0
        pos_entry_ts: int = 0
        total_pnl: float = 0.0
        trades: int = 0

        logs_dir = Path("logs/replay_obflow")
        logs_dir.mkdir(parents=True, exist_ok=True)
        ev_path = self.cfg.out_path or (logs_dir / f"{self.cfg.symbol}.jsonl")
        out = ev_path.open("w")

        start = time.time()
        for ev in ws.orderbook_stream():
            if (time.time() - start) >= self.cfg.max_sec:
                break
            etype = ev.get("type")
            if etype == "snapshot":
                apply_snapshot(
                    book,
                    int(ev.get("seq", 0)),
                    int(ev.get("ts", 0)),
                    ((float(p), float(s)) for p, s in ev.get("bids", [])),
                    ((float(p), float(s)) for p, s in ev.get("asks", [])),
                )
            elif etype == "delta":
                if not apply_delta(
                    book,
                    int(ev.get("seq", 0)),
                    int(ev.get("ts", 0)),
                    ((float(p), float(s)) for p, s in ev.get("bids", [])),
                    ((float(p), float(s)) for p, s in ev.get("asks", [])),
                ):
                    continue
            else:
                continue

            now_sec = int(time.time())
            px = self._micro(book)

            if state is not None and pos_side is not None and pos_qty > 0.0:
                acts = state.update(px=px, now_ts=now_sec)
                for a in acts:
                    a["ts"] = now_sec
                    a["symbol"] = self.cfg.symbol
                    out.write(json.dumps(a) + "\n")
                    out.flush()
                    if a["type"] in {"partial_close", "time_stop_close"}:
                        close_qty = float(a.get("qty", 0.0))
                        if close_qty > 0.0:
                            if pos_side == "BUY":
                                pnl = (px - pos_entry) * close_qty
                            else:
                                pnl = (pos_entry - px) * close_qty
                            total_pnl += pnl
                            pos_qty -= close_qty
                            if pos_qty <= 1e-12:
                                cooldown.on_trade_close(pnl=total_pnl, now_ts=now_sec)
                                state = None
                                pos_side = None
                                pos_qty = 0.0
                                pos_entry = 0.0
                                trades += 1

            if state is None and cooldown.can_trade(now_sec):
                sig = decide(book, ob_cfg)
                if sig is not None:
                    entry_px = max(px, 1e-9)
                    qty = max(0.0, self.cfg.qty_usdt / entry_px)
                    if qty > 0.0:
                        pos_side = str(sig["side"]).upper()
                        pos_qty = qty
                        pos_entry = entry_px
                        pos_entry_ts = now_sec
                        state = TradeState(
                            side=pos_side,
                            entry_price=pos_entry,
                            qty=pos_qty,
                            entry_ts=pos_entry_ts,
                            params=TradeParams(
                                tp1=float(runtime.params.entry_exit.tp1),
                                trail_after_tp1=float(runtime.params.entry_exit.trail_after_tp1),
                                time_stop_sec=15 * 60,
                                partial_pct=0.5,
                            ),
                        )
                        out.write(
                            json.dumps(
                                {
                                    "ts": now_sec,
                                    "type": "open",
                                    "symbol": self.cfg.symbol,
                                    "side": pos_side,
                                    "qty": pos_qty,
                                    "price": pos_entry,
                                    "signal": sig,
                                }
                            )
                            + "\n"
                        )
                        out.flush()

        out.close()
        reports = Path("reports")
        reports.mkdir(exist_ok=True)
        summary = {
            "symbol": self.cfg.symbol,
            "trades": trades,
            "pnl": round(total_pnl, 8),
            "log_file": str(ev_path),
        }
        (reports / f"replay_obflow_{self.cfg.symbol}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2)
        )
        return summary
