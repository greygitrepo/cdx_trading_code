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
        return float(os.environ.get(name, str(default)))
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
    notional = max_notional
    # Linear USDT perps: qty = notional * leverage / price
    qty = max(0.0, (notional * lev) / max(last_price, 1e-9))

    if prefer_limit:
        # Place passively one tick inside best bid/ask approximation
        price = last_price * (0.9995 if side == "BUY" else 1.0005)
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
