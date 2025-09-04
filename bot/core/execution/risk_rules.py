"""Simple risk rules for live execution.

Rules implemented:
- Block entries if free balance below threshold
- Cap order notional to max allocation percentage of equity
- Slippage guard: compare intended price vs reference (e.g., mid) and block if over threshold
- Apply TP/SL parameters helper

Environment variables used (with defaults reasonable for testnet):
- MAX_ALLOC_PCT (default 0.05)
- MIN_FREE_BALANCE_USDT (default 100)
- SLIPPAGE_GUARD_PCT (default 0.003)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


@dataclass
class RiskContext:
    equity_usdt: float
    free_usdt: float
    symbol: str
    last_mid: Optional[float] = None


def max_alloc_notional(equity_usdt: float) -> float:
    max_alloc_pct = _env_float("MAX_ALLOC_PCT", 0.05)
    return equity_usdt * max_alloc_pct


def check_balance_guard(ctx: RiskContext) -> tuple[bool, str]:
    min_free = _env_float("MIN_FREE_BALANCE_USDT", 100.0)
    if ctx.free_usdt < min_free:
        return False, f"Free balance {ctx.free_usdt:.2f} < minimum {min_free:.2f} USDT"
    return True, "ok"


def check_order_size(notional_usdt: float, equity_usdt: float) -> tuple[bool, str]:
    cap = max_alloc_notional(equity_usdt)
    if notional_usdt > cap:
        return False, f"Order notional {notional_usdt:.2f} exceeds cap {cap:.2f} (MAX_ALLOC_PCT)"
    return True, "ok"


def slippage_guard(intended_price: float, reference_price: float) -> tuple[bool, str]:
    if reference_price <= 0:
        return False, "Reference price invalid"
    slip = abs(intended_price - reference_price) / reference_price
    limit = _env_float("SLIPPAGE_GUARD_PCT", 0.003)
    if slip > limit:
        return False, f"Slippage {slip:.4f} > limit {limit:.4f}"
    return True, "ok"


def compute_tp_sl(entry_price: float, side: str, *, tp_pct: float, sl_pct: float) -> tuple[float, float]:
    if side.upper() == "BUY":
        tp = entry_price * (1 + tp_pct)
        sl = entry_price * (1 - sl_pct)
    else:
        tp = entry_price * (1 - tp_pct)
        sl = entry_price * (1 + sl_pct)
    return tp, sl

