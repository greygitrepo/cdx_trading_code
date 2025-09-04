"""Unit test for partial fills and PnL/fees integration."""

from __future__ import annotations

import pytest
from bot.core.backtest import Engine
from bot.core.fees import SimpleFeeModel, SimpleSlippage
from bot.core.types import Account, Order, OrderType, Side, Tick


def test_partial_fill_accumulates_and_updates_position() -> None:
    acc = Account(balance=100.0)
    engine = Engine(
        account=acc,
        fee_model=SimpleFeeModel(maker=0.0002, taker=0.00055),
        slippage=SimpleSlippage(maker_bps=0.0, taker_bps=0.0),
    )

    order = Order(side=Side.BUY, qty=10.0, type=OrderType.LIMIT, limit_price=100.0)
    engine.place(order)

    ticks = [
        Tick(ts=1, bid=99.9, ask=100.0, last=100.0, bid_sz=10.0, ask_sz=3.0),
        Tick(ts=2, bid=100.0, ask=100.0, last=100.0, bid_sz=10.0, ask_sz=4.0),
        Tick(ts=3, bid=100.0, ask=100.0, last=100.0, bid_sz=10.0, ask_sz=5.0),
    ]
    liquidities = [3.0, 4.0, 3.0]

    engine.run(ticks, liquidities)

    # Expect total filled 10
    total_qty = sum(f.qty for f in engine.fills)
    assert total_qty == 10.0
    assert acc.position.qty == 10.0
    # Avg price ~ 100.0 without slippage
    assert acc.position.avg_price == 100.0
    # Fees charged (all taker): 10 * 100 * 0.00055 = 0.55
    assert acc.position.fees_paid == 10.0 * 100.0 * 0.00055
    # Allow tiny float rounding
    assert acc.balance == pytest.approx(
        100.0 - acc.position.fees_paid, rel=1e-12, abs=1e-12
    )
