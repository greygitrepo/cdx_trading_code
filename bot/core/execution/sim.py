"""Execution helpers built on the backtest engine for simulation."""

from __future__ import annotations

from ..backtest import Engine
from ..fees import SimpleFeeModel, SimpleSlippage
from ..types import Account, Order, OrderType, Side, Tick


def simulate_trade() -> str:
    """Return placeholder fill message for legacy tests."""
    return "filled"


def simulate_limit_fill() -> float:
    """Place a small limit order that gets partially filled and return filled qty."""
    acc = Account(balance=100.0)
    engine = Engine(account=acc, fee_model=SimpleFeeModel(), slippage=SimpleSlippage())
    order = Order(side=Side.BUY, qty=5.0, type=OrderType.LIMIT, limit_price=100.0)
    engine.place(order)
    ticks = [
        Tick(ts=1, bid=99.5, ask=100.0, last=100.0, bid_sz=2.0, ask_sz=1.0),
        Tick(ts=2, bid=99.6, ask=100.0, last=100.0, bid_sz=2.0, ask_sz=3.0),
    ]
    liquidities = [1.0, 2.0]
    engine.run(ticks, liquidities)
    filled_qty = sum(f.qty for f in engine.fills)
    return filled_qty
