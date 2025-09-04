"""Unit tests for fee and slippage models."""

from __future__ import annotations

from bot.core.fees import SimpleFeeModel, SimpleSlippage
from bot.core.types import Side, Tick


def test_fee_model_amounts() -> None:
    fm = SimpleFeeModel(maker=0.0002, taker=0.00055)
    assert fm.fee(10_000.0, is_maker=True) == 2.0
    assert fm.fee(10_000.0, is_maker=False) == 5.5


def test_slippage_prices() -> None:
    sl = SimpleSlippage(maker_bps=0.0, taker_bps=1.0)
    tick = Tick(ts=0, bid=100.0, ask=100.1, last=100.05)
    filled, price, is_maker = sl.fill(Side.BUY, 1.0, tick, available_liquidity=1.0)
    assert filled == 1.0
    assert is_maker is False
    # 1 bps on ask side
    assert price > tick.ask
