from __future__ import annotations

import pytest


pytestmark = [pytest.mark.strategy, pytest.mark.unit]


def test_slippage_guard_and_tp_sl():
    from bot.core.execution.risk_rules import slippage_guard, compute_tp_sl

    ok, _ = slippage_guard(101.0, 100.0)
    assert not ok  # default limit 0.3% -> 1% should fail
    tp, sl = compute_tp_sl(100.0, "BUY", tp_pct=0.01, sl_pct=0.02)
    assert tp == 101.0 and sl == 98.0


def test_position_sizer_rounding():
    from bot.risk.position_sizer import compute_order_qty

    sized = compute_order_qty(
        100.0, 200.0, leverage=5.0, lot_step=0.1, tick_size=0.01, min_qty=0.1
    )
    # raw qty = (200*5)/100 = 10 -> step 0.1 -> 10
    assert abs(sized.qty - 10.0) < 1e-9
