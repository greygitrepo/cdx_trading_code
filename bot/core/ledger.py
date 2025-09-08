from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import csv
import json
import time


@dataclass
class TradeRecord:
    trade_id: str
    symbol: str
    side: str  # LONG/SHORT
    entry_time: int
    entry_price: float
    entry_qty: float
    entry_value_usdt: float
    entry_liquidity: Optional[str] = None  # maker/taker
    entry_fee_usdt: float = 0.0
    entry_slippage_pct: float = 0.0

    exit_time: Optional[int] = None
    exit_price: float = 0.0
    exit_qty: float = 0.0
    exit_value_usdt: float = 0.0
    exit_liquidity: Optional[str] = None
    exit_fee_usdt: float = 0.0
    exit_slippage_pct: float = 0.0
    exit_reason: Optional[str] = None

    hold_secs: Optional[int] = None
    realized_pnl_usdt: float = 0.0
    realized_pnl_pct_on_value: float = 0.0
    max_favorable_excursion_pct: float = 0.0
    max_adverse_excursion_pct: float = 0.0
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_canceled: int = 0

    # Market context at entry (best-effort)
    spread_pct_at_entry: Optional[float] = None
    imbalance_L5: Optional[float] = None
    depth_L5_bid_usd: Optional[float] = None
    depth_L5_ask_usd: Optional[float] = None
    tps_entry: Optional[float] = None
    volatility_1m_pct: Optional[float] = None
    volatility_5m_pct: Optional[float] = None
    funding_min_to_next: Optional[float] = None

    # Trail diagnostics
    trail_armed_at_price: Optional[float] = None
    trail_steps: int = 0
    max_trail_offset_pct: Optional[float] = None


@dataclass
class TradeLedger:
    run_id: str
    out_dir: Path
    active: dict[str, TradeRecord] = field(default_factory=dict)  # key by symbol

    def _date_paths(self) -> tuple[Path, Path]:
        ts = time.gmtime()
        date = f"{ts.tm_year:04d}-{ts.tm_mon:02d}-{ts.tm_mday:02d}"
        csv_path = self.out_dir / f"trades_{date}.csv"
        jsonl_path = self.out_dir / f"trades_{date}.jsonl"
        return csv_path, jsonl_path

    def _ensure_csv_header(self, fp: Path) -> None:
        if fp.exists():
            return
        fp.parent.mkdir(parents=True, exist_ok=True)
        with fp.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "trade_id","symbol","side","entry_time","entry_price","entry_qty","entry_value_usdt",
                "entry_liquidity","entry_fee_usdt","entry_slippage_pct","exit_time","exit_price",
                "exit_qty","exit_value_usdt","exit_liquidity","exit_fee_usdt","exit_slippage_pct",
                "exit_reason","hold_secs","realized_pnl_usdt","realized_pnl_pct_on_value","MFE_pct","MAE_pct",
                "orders_submitted","orders_filled","orders_canceled","spread_pct_at_entry","depth_L5_bid_usd",
                "depth_L5_ask_usd","imbalance_L5","tps_entry","volatility_1m_pct","volatility_5m_pct","funding_min_to_next"
            ])

    def on_entry(
        self,
        *,
        symbol: str,
        side_long: bool,
        entry_ts: int,
        price: float,
        qty: float,
        spread_pct: Optional[float] = None,
        imbalance_L5: Optional[float] = None,
        depth_bid_usd: Optional[float] = None,
        depth_ask_usd: Optional[float] = None,
        tps_entry: Optional[float] = None,
        entry_liquidity: Optional[str] = None,
        entry_fee_usdt: float = 0.0,
        entry_slippage_pct: float = 0.0,
    ) -> TradeRecord:
        tid = f"{self.run_id}_{symbol}_{entry_ts}"
        rec = TradeRecord(
            trade_id=tid,
            symbol=symbol,
            side=("LONG" if side_long else "SHORT"),
            entry_time=entry_ts,
            entry_price=price,
            entry_qty=qty,
            entry_value_usdt=price * qty,
            entry_liquidity=entry_liquidity,
            entry_fee_usdt=entry_fee_usdt,
            entry_slippage_pct=entry_slippage_pct,
            spread_pct_at_entry=spread_pct,
            imbalance_L5=imbalance_L5,
            depth_L5_bid_usd=depth_bid_usd,
            depth_L5_ask_usd=depth_ask_usd,
            tps_entry=tps_entry,
        )
        self.active[symbol] = rec
        return rec

    def update_mfe_mae(self, symbol: str, now_price: float) -> None:
        rec = self.active.get(symbol)
        if not rec:
            return
        change = (now_price - rec.entry_price) / rec.entry_price if rec.side == "LONG" else (rec.entry_price - now_price) / rec.entry_price
        rec.max_favorable_excursion_pct = max(rec.max_favorable_excursion_pct, change)
        rec.max_adverse_excursion_pct = min(rec.max_adverse_excursion_pct, change)

    def on_exit(
        self,
        *,
        symbol: str,
        exit_ts: int,
        price: float,
        qty: float,
        reason: str,
        exit_liquidity: Optional[str] = None,
        exit_fee_usdt: float = 0.0,
        exit_slippage_pct: float = 0.0,
        realized_pnl_usdt: float = 0.0,
    ) -> Optional[TradeRecord]:
        rec = self.active.pop(symbol, None)
        if not rec:
            return None
        rec.exit_time = exit_ts
        rec.exit_price = price
        rec.exit_qty = qty
        rec.exit_value_usdt = price * qty
        rec.exit_reason = reason
        rec.exit_liquidity = exit_liquidity
        rec.exit_fee_usdt = exit_fee_usdt
        rec.exit_slippage_pct = exit_slippage_pct
        rec.hold_secs = max(0, int((exit_ts - rec.entry_time) / 1000))
        rec.realized_pnl_usdt = realized_pnl_usdt
        if rec.entry_value_usdt > 0:
            rec.realized_pnl_pct_on_value = realized_pnl_usdt / rec.entry_value_usdt
        self._write(rec)
        return rec

    def _write(self, rec: TradeRecord) -> None:
        csv_path, jsonl_path = self._date_paths()
        self._ensure_csv_header(csv_path)
        with csv_path.open("a", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                rec.trade_id, rec.symbol, rec.side, rec.entry_time, f"{rec.entry_price:.6f}", f"{rec.entry_qty:.8f}", f"{rec.entry_value_usdt:.6f}",
                rec.entry_liquidity or "", f"{rec.entry_fee_usdt:.6f}", f"{rec.entry_slippage_pct:.6f}", rec.exit_time or 0,
                f"{rec.exit_price:.6f}", f"{rec.exit_qty:.8f}", f"{rec.exit_value_usdt:.6f}", rec.exit_liquidity or "",
                f"{rec.exit_fee_usdt:.6f}", f"{rec.exit_slippage_pct:.6f}", rec.exit_reason or "", rec.hold_secs or 0,
                f"{rec.realized_pnl_usdt:.6f}", f"{rec.realized_pnl_pct_on_value:.6f}", f"{rec.max_favorable_excursion_pct:.6f}", f"{rec.max_adverse_excursion_pct:.6f}",
                rec.orders_submitted, rec.orders_filled, rec.orders_canceled,
                f"{(rec.spread_pct_at_entry or 0.0):.6f}", rec.depth_L5_bid_usd or "", rec.depth_L5_ask_usd or "",
                rec.imbalance_L5 or "", rec.tps_entry or "", rec.volatility_1m_pct or "", rec.volatility_5m_pct or "", rec.funding_min_to_next or "",
            ])
        with jsonl_path.open("a", encoding="utf-8") as f:
            obj = rec.__dict__.copy()
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

