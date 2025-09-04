"""Position sizing utility for linear USDT perps.

Computes order quantity from per-symbol budget, leverage, and market rules
(tick size, lot step, and minimums). Rounds conservatively to avoid rejections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def _floor_step(value: float, step: Optional[float]) -> float:
    if not step or step <= 0:
        return value
    return (int(value / step)) * step


def _ceil_step(value: float, step: Optional[float]) -> float:
    if not step or step <= 0:
        return value
    # implement ceil without importing math for fractional steps
    q = int(value / step)
    if abs(q * step - value) < 1e-12:
        return value
    return (q + 1) * step


@dataclass
class SizedOrder:
    qty: float
    est_notional: float
    used_budget: float


def compute_order_qty(
    symbol_price: float,
    budget_usdt: float,
    *,
    leverage: float,
    lot_step: Optional[float],
    tick_size: Optional[float],
    min_qty: Optional[float] = None,
    min_notional: Optional[float] = None,
) -> SizedOrder:
    """Return qty sized from budget and leverage respecting steps/minimums.

    - For linear USDT perps: qty = (budget * leverage) / price
    - Floor to lot_step to avoid overprecision
    - Enforce min_qty and min_notional conservatively (ceil where needed)
    """
    price = max(symbol_price, 1e-9)
    raw_qty = max(0.0, (budget_usdt * leverage) / price)
    qty = _floor_step(raw_qty, lot_step)
    if min_qty and qty < min_qty:
        qty = min_qty if not lot_step else _ceil_step(min_qty, lot_step)
    # Ensure min notional if known
    if min_notional and qty * price < min_notional:
        target_qty = min_notional / price
        qty = target_qty if not lot_step else _ceil_step(target_qty, lot_step)
    est_notional = qty * price
    # used_budget is est_notional / leverage (best effort)
    used_budget = est_notional / max(leverage, 1e-9)
    return SizedOrder(qty=qty, est_notional=est_notional, used_budget=used_budget)
