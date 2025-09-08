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
    entry_mid_ref: Optional[float] = None

    exit_time: Optional[int] = None
    exit_price: float = 0.0
    exit_qty: float = 0.0
    exit_value_usdt: float = 0.0
    exit_liquidity: Optional[str] = None
    exit_fee_usdt: float = 0.0
    exit_slippage_pct: float = 0.0
    exit_mid_ref: Optional[float] = None
    exit_reason: Optional[str] = None

    hold_secs: Optional[int] = None
    realized_pnl_usdt: float = 0.0
    realized_pnl_pct_on_value: float = 0.0
    max_favorable_excursion_pct: float = 0.0
    max_adverse_excursion_pct: float = 0.0
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_canceled: int = 0
    entry_links: list[str] = field(default_factory=list)
    exit_links: list[str] = field(default_factory=list)
    entry_qty_filled: float = 0.0
    exit_qty_filled: float = 0.0
    link_labels: dict[str, str] = field(default_factory=dict)  # orderLinkId -> label (entry/partial_close/time_stop/...)

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
    tp_abs: Optional[float] = None
    sl_abs: Optional[float] = None
    trail_abs: Optional[float] = None


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
        entry_mid_ref: Optional[float] = None,
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
            entry_mid_ref=entry_mid_ref,
            spread_pct_at_entry=spread_pct,
            imbalance_L5=imbalance_L5,
            depth_L5_bid_usd=depth_bid_usd,
            depth_L5_ask_usd=depth_ask_usd,
            tps_entry=tps_entry,
        )
        self.active[symbol] = rec
        return rec

    def on_order_submitted(self, symbol: str, order_link_id: str, *, for_entry: bool, label: str | None = None) -> None:
        rec = self.active.get(symbol)
        if not rec:
            return
        rec.orders_submitted += 1
        if order_link_id:
            (rec.entry_links if for_entry else rec.exit_links).append(order_link_id)
            if label:
                rec.link_labels[order_link_id] = label

    def on_order_canceled(self, symbol: str) -> None:
        rec = self.active.get(symbol)
        if not rec:
            return
        rec.orders_canceled += 1

    def on_execution(
        self,
        *,
        symbol: str,
        side: str,  # BUY/SELL
        price: float,
        qty: float,
        fee_usdt: float,
        is_maker: bool,
        order_link_id: str | None,
        mid_ref: float | None = None,
    ) -> None:
        rec = self.active.get(symbol)
        if not rec or qty <= 0 or price <= 0:
            return
        rec.orders_filled += 1
        side_long = rec.side == "LONG"
        is_entry_leg = (side == "BUY" and side_long) or (side == "SELL" and (not side_long))
        if is_entry_leg:
            rec.entry_fee_usdt += fee_usdt
            rec.entry_qty_filled += qty
            if mid_ref and mid_ref > 0 and rec.entry_mid_ref:
                # weighted average slippage vs entry mid
                base = rec.entry_mid_ref
                slip = (price - base) / base if side == "BUY" else (base - price) / base
                # running avg
                total_qty = max(1e-12, rec.entry_qty_filled)
                rec.entry_slippage_pct = ((rec.entry_slippage_pct * (total_qty - qty)) + (slip * qty)) / total_qty
            if is_maker and not rec.entry_liquidity:
                rec.entry_liquidity = "maker"
            elif rec.entry_liquidity is None and not is_maker:
                rec.entry_liquidity = "taker"
        else:
            rec.exit_fee_usdt += fee_usdt
            rec.exit_qty_filled += qty
            if mid_ref and mid_ref > 0 and rec.exit_mid_ref:
                base = rec.exit_mid_ref
                slip = (price - base) / base if side == "SELL" else (base - price) / base
                total_qty = max(1e-12, rec.exit_qty_filled)
                rec.exit_slippage_pct = ((rec.exit_slippage_pct * (total_qty - qty)) + (slip * qty)) / total_qty
            if is_maker and not rec.exit_liquidity:
                rec.exit_liquidity = "maker"
            elif rec.exit_liquidity is None and not is_maker:
                rec.exit_liquidity = "taker"

    def update_mfe_mae(self, symbol: str, now_price: float) -> None:
        rec = self.active.get(symbol)
        if not rec:
            return
        change = (now_price - rec.entry_price) / rec.entry_price if rec.side == "LONG" else (rec.entry_price - now_price) / rec.entry_price
        rec.max_favorable_excursion_pct = max(rec.max_favorable_excursion_pct, change)
        rec.max_adverse_excursion_pct = min(rec.max_adverse_excursion_pct, change)

    def set_stops(self, symbol: str, *, tp_abs: Optional[float], sl_abs: Optional[float], trail_abs: Optional[float]) -> None:
        rec = self.active.get(symbol)
        if not rec:
            return
        rec.tp_abs = tp_abs
        rec.sl_abs = sl_abs
        rec.trail_abs = trail_abs

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
        exit_mid_ref: Optional[float] = None,
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
        rec.exit_mid_ref = exit_mid_ref
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

    def write_daily_summary(self) -> None:
        """Compute simple daily summary from today's CSV and write JSON next to it."""
        csv_path, jsonl_path = self._date_paths()
        if not csv_path.exists():
            return
        trades = 0
        wins = 0
        losses = 0
        pnl_list: list[float] = []
        fees: float = 0.0
        hold_secs: list[int] = []
        entry_liqs: list[str] = []
        exit_liqs: list[str] = []
        # For taker slippage
        taker_slip_numer = 0.0
        taker_slip_denom = 0.0
        # Equity curve for DD
        curve: list[float] = []
        cum = 0.0
        with csv_path.open() as f:
            r = csv.DictReader(f)
            for row in r:
                try:
                    trades += 1
                    pnl = float(row["realized_pnl_usdt"])
                    pnl_list.append(pnl)
                    wins += 1 if pnl > 0 else 0
                    losses += 1 if pnl < 0 else 0
                    fees += float(row.get("entry_fee_usdt", 0.0) or 0.0) + float(row.get("exit_fee_usdt", 0.0) or 0.0)
                    hs = int(row.get("hold_secs", 0) or 0)
                    hold_secs.append(hs)
                    el = (row.get("entry_liquidity") or "").lower()
                    xl = (row.get("exit_liquidity") or "").lower()
                    entry_liqs.append(el)
                    exit_liqs.append(xl)
                    try:
                        eqf = float(row.get("entry_qty_filled", 0.0) or 0.0)
                        exqf = float(row.get("exit_qty_filled", 0.0) or 0.0)
                        eslip = float(row.get("entry_slippage_pct", 0.0) or 0.0)
                        xslip = float(row.get("exit_slippage_pct", 0.0) or 0.0)
                        if el == "taker" and eqf > 0:
                            taker_slip_numer += eslip * eqf
                            taker_slip_denom += eqf
                        if xl == "taker" and exqf > 0:
                            taker_slip_numer += xslip * exqf
                            taker_slip_denom += exqf
                    except Exception:
                        pass
                    cum += pnl
                    curve.append(cum)
                except Exception:
                    continue
        def _dd(xs: list[float]) -> float:
            peak = -1e18
            mdd = 0.0
            for v in xs:
                if v > peak:
                    peak = v
                mdd = min(mdd, v - peak)
            return mdd
        date = csv_path.stem.split("trades_")[-1]
        gross = sum(pnl_list)
        net = gross  # fees already embedded in realized if we passed net; else subtract fees
        wr = (wins / trades) if trades else 0.0
        avg_win = (sum(p for p in pnl_list if p > 0) / wins) if wins else 0.0
        avg_loss = (sum(-p for p in pnl_list if p < 0) / losses) if losses else 0.0
        rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0
        expectancy = wr * avg_win - (1 - wr) * avg_loss
        dd = _dd(curve)
        pf = (sum(p for p in pnl_list if p > 0) / sum(-p for p in pnl_list if p < 0)) if losses else 0.0
        def _ratio(liqs: list[str], key: str) -> float:
            n = sum(1 for x in liqs if x == key)
            return (n / len(liqs)) if liqs else 0.0
        summary = {
            "date": date,
            "trades": trades,
            "win": wins,
            "loss": losses,
            "win_rate": wr,
            "avg_win_usdt": avg_win,
            "avg_loss_usdt": avg_loss,
            "RR": rr,
            "expectancy_usdt": expectancy,
            "gross_pnl_usdt": gross,
            "fees_usdt": fees,
            "net_pnl_usdt": net,
            "max_drawdown_usdt": dd,
            "profit_factor": pf,
            "holding_time_median_secs": (sorted(hold_secs)[len(hold_secs)//2] if hold_secs else 0),
            "maker_ratio_entry": _ratio(entry_liqs, "maker"),
            "maker_ratio_exit": _ratio(exit_liqs, "maker"),
            "avg_slippage_taker_pct": (taker_slip_numer / taker_slip_denom) if taker_slip_denom > 0 else 0.0,
        }
        out = self.out_dir / f"summary_{date}.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
