"""Strategy-to-execution adapter.

Converts strategy signals (e.g., +1/-1) into order parameters for Bybit v5.
Separates symbol/leverage/size calculation and TP/SL calculation.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from .execution.risk_rules import compute_tp_sl


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name, str(default))
        val = raw.split("#", 1)[0].strip()
        return float(val) if val != "" else float(default)
    except Exception:
        return default


@dataclass
class OrderPlan:
    symbol: str
    side: str  # BUY or SELL
    qty: float
    order_type: str  # Market or Limit
    tif: str  # GTC/IOC/PostOnly
    price: Optional[float]
    order_link_id: str
    tp: Optional[float]
    sl: Optional[float]


def _round_to_step(value: float, step: Optional[float]) -> float:
    if not step or step <= 0:
        return value
    # Floor to the nearest step to avoid over-precision
    return (int(value / step)) * step


def build_order_plan(
    *,
    signal: int,
    last_price: float,
    equity_usdt: float,
    symbol: Optional[str] = None,
    leverage: Optional[float] = None,
    max_alloc_pct: Optional[float] = None,
    tp_pct: float = 0.002,
    sl_pct: float = 0.002,
    prefer_limit: bool = False,
    post_only: bool = False,
    # optional exchange filters for precision/limits
    price_tick: Optional[float] = None,
    qty_step: Optional[float] = None,
    min_qty: Optional[float] = None,
    # optional fixed notional override (USDT)
    fixed_notional_usdt: Optional[float] = None,
) -> OrderPlan:
    """Build an order plan from a directional signal.

    - signal: +1 for long, -1 for short, 0 no-op
    - qty sized by max allocation and leverage (linear USDT perp assumed)
    """
    sym = symbol or os.environ.get("BYBIT_SYMBOL", "BTCUSDT")
    lev = leverage or _env_float("LEVERAGE", 10)
    alloc = max_alloc_pct or _env_float("MAX_ALLOC_PCT", 0.05)

    side = "BUY" if signal > 0 else "SELL"
    max_notional = equity_usdt * alloc
    notional = fixed_notional_usdt if (fixed_notional_usdt is not None and fixed_notional_usdt > 0) else max_notional
    # Linear USDT perps: qty = notional * leverage / price
    qty = max(0.0, (notional * lev) / max(last_price, 1e-9))
    # Apply precision/limits if provided
    if qty_step:
        qty = _round_to_step(qty, qty_step)
    if min_qty and qty < min_qty:
        qty = min_qty

    if prefer_limit:
        # Place passively one tick inside best bid/ask approximation
        raw_price = last_price * (0.9995 if side == "BUY" else 1.0005)
        price = _round_to_step(raw_price, price_tick)
        tif = "PostOnly" if post_only else "GTC"
        order_type = "Limit"
    else:
        price = None
        tif = "IOC"
        order_type = "Market"

    order_link_id = f"cdx-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    tp, sl = compute_tp_sl(last_price, side, tp_pct=tp_pct, sl_pct=sl_pct)

    return OrderPlan(
        symbol=sym,
        side=side,
        qty=qty,
        order_type=order_type,
        tif=tif,
        price=price,
        order_link_id=order_link_id,
        tp=tp,
        sl=sl,
    )
