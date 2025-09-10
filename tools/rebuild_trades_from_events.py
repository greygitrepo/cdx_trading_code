from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bot.core.reporting.ledger import TradeLedgerRow
from bot.core.reporting.writer import TradeLedgerWriter


def load_events(fp: Path) -> List[Dict[str, Any]]:
    evs: List[Dict[str, Any]] = []
    if not fp.exists():
        return evs
    with fp.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evs.append(json.loads(line))
            except Exception:
                continue
    return evs


def reconstruct_trades(run_id: str, events: List[Dict[str, Any]]) -> List[TradeLedgerRow]:
    # Minimal state per symbol
    state: Dict[str, Dict[str, Any]] = {}
    out: List[TradeLedgerRow] = []

    for e in events:
        sym = e.get("symbol")
        if not sym:
            continue
        step = e.get("step")
        ts = int(e.get("ts", 0))
        meta = e.get("meta") or {}
        st = state.setdefault(sym, {
            "pos_qty": 0.0,
            "side": None,
            "entry_ts": None,
            "entry_px_sum": 0.0,
            "entry_qty": 0.0,
            "orders_submitted": 0,
            "orders_filled": 0,
            "orders_canceled": 0,
            "mfe": 0.0,
            "mae": 0.0,
            "entry_spread_pct": 0.0,
        })

        if step == "order":
            st["orders_submitted"] += 1
        elif step == "cancel":
            st["orders_canceled"] += 1
        elif step == "fill":
            side = str(meta.get("side", "")).upper()
            price = float(meta.get("price") or 0.0)
            qty = float(meta.get("qty") or 0.0)
            if price <= 0 or qty <= 0 or side not in {"BUY", "SELL"}:
                continue
            st["orders_filled"] += 1
            if st["pos_qty"] == 0:
                # Start of a trade
                st["side"] = "LONG" if side == "BUY" else "SHORT"
                st["entry_ts"] = ts
                st["entry_px_sum"] = price * qty
                st["entry_qty"] = qty
                st["pos_qty"] = qty if side == "BUY" else -qty
            else:
                # Accumulate towards close if opposite
                delta = qty if side == "BUY" else -qty
                st["pos_qty"] += delta
                # If pos flips sign or returns to zero, close trade
                if abs(st["pos_qty"]) <= 1e-9:
                    # Close
                    entry_qty = float(st["entry_qty"]) or 0.0
                    entry_price = (float(st["entry_px_sum"]) / max(1e-12, entry_qty)) if entry_qty > 0 else price
                    side_long = st["side"] == "LONG"
                    exit_price = price
                    # Fees/liquidity unknown from events → fill as 0/None
                    pnl = (exit_price - entry_price) * entry_qty if side_long else (entry_price - exit_price) * entry_qty
                    row = TradeLedgerRow(
                        trade_id=f"{run_id}:{sym}:{int(st['entry_ts'] or ts)}",
                        run_id=run_id,
                        symbol=sym,
                        side=("LONG" if side_long else "SHORT"),
                        entry_time=int(st["entry_ts"] or ts),
                        entry_price=float(entry_price),
                        entry_qty=float(entry_qty),
                        entry_value_usdt=float(entry_price * entry_qty),
                        entry_liquidity=None,
                        entry_fee_usdt=0.0,
                        entry_slippage_pct=0.0,
                        exit_time=int(ts),
                        exit_price=float(exit_price),
                        exit_qty=float(entry_qty),
                        exit_value_usdt=float(exit_price * entry_qty),
                        exit_liquidity=None,
                        exit_fee_usdt=0.0,
                        exit_slippage_pct=0.0,
                        exit_reason="MANUAL",
                        hold_secs=float(max(0, (ts - int(st["entry_ts"] or ts)) / 1000)),
                        realized_pnl_usdt=float(pnl),
                        realized_pnl_pct_on_value=(pnl / max(1e-12, entry_price * entry_qty)) * 100.0,
                        max_favorable_excursion_pct=float(st.get("mfe", 0.0)) * 100.0,
                        max_adverse_excursion_pct=float(st.get("mae", 0.0)) * 100.0,
                        orders_submitted=int(st.get("orders_submitted", 0)),
                        orders_filled=int(st.get("orders_filled", 0)),
                        orders_canceled=int(st.get("orders_canceled", 0)),
                        spread_pct_at_entry=float(st.get("entry_spread_pct", 0.0)) * 100.0,
                        depth_L5_bid_usd=0.0,
                        depth_L5_ask_usd=0.0,
                        imbalance_L5=0.0,
                        tps_entry=0.0,
                        volatility_1m_pct=0.0,
                        volatility_5m_pct=0.0,
                        funding_min_to_next=None,
                        trail_armed_at_price=None,
                        trail_steps=None,
                        max_trail_offset_pct=None,
                    )
                    out.append(row)
                    # Reset
                    state[sym] = {
                        "pos_qty": 0.0,
                        "side": None,
                        "entry_ts": None,
                        "entry_px_sum": 0.0,
                        "entry_qty": 0.0,
                        "orders_submitted": 0,
                        "orders_filled": 0,
                        "orders_canceled": 0,
                        "mfe": 0.0,
                        "mae": 0.0,
                        "entry_spread_pct": 0.0,
                    }
        elif step == "pnl":
            # Not used for reconstruction beyond potential diagnostics
            pass
        elif step == "info":
            # May contain orderbook context at entry; if we see it immediately after an order plan, capture spread
            tag = (e.get("step") or "").lower()
            # Kept as future extension
            pass

    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild trades.csv/jsonl from events.jsonl")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True, help="Output directory, e.g., logs/run_<RUN_ID>")
    args = ap.parse_args()

    run_id = args.run_id
    out_dir = Path(args.out)
    events_fp = Path("logs") / run_id / "events.jsonl"
    events = load_events(events_fp)
    rows = reconstruct_trades(run_id, events)
    writer = TradeLedgerWriter(run_id, str(out_dir))
    for row in rows:
        writer.append(row, formats=("csv", "jsonl"))


if __name__ == "__main__":
    main()

