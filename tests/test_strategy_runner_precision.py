from __future__ import annotations

from bot.core.strategy_runner import build_order_plan


def test_precision_rounding_and_min_qty():
    plan = build_order_plan(
        signal=+1,
        last_price=25000.0,
        equity_usdt=1000.0,
        symbol="BTCUSDT",
        leverage=10,
        price_tick=0.5,
        qty_step=0.001,
        min_qty=0.005,
        prefer_limit=True,
    )
    # qty should be rounded to 0.001 steps and at least 0.005
    assert plan.qty >= 0.005
    assert abs((plan.qty / 0.001) - round(plan.qty / 0.001)) < 1e-9
    # price should be rounded to 0.5 tick
    assert abs((plan.price / 0.5) - round(plan.price / 0.5)) < 1e-9
