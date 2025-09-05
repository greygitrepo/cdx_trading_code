from __future__ import annotations

from bot.core.execution.trade_state import TradeParams, TradeState, Cooldown


def test_trade_state_partial_and_trailing() -> None:
    tp = TradeParams(tp1=0.01, trail_after_tp1=0.005, time_stop_sec=3600, partial_pct=0.5)
    st = TradeState(side="BUY", entry_price=100.0, qty=2.0, entry_ts=0, params=tp)

    # Price hits TP1, expect partial close of 1.0
    acts = st.update(px=101.0, now_ts=10)
    assert any(a["type"] == "partial_close" and abs(a["qty"] - 1.0) < 1e-9 for a in acts)

    # Move anchor up, then fall to trigger trailing stop for remaining 1.0
    _ = st.update(px=102.0, now_ts=20)
    stop = 102.0 * (1 - tp.trail_after_tp1)
    acts2 = st.update(px=stop * 0.999, now_ts=30)
    assert any(a["reason"] == "trail_stop" for a in acts2)
    assert st.realized_qty == st.qty


def test_cooldown_on_consecutive_losses() -> None:
    cd = Cooldown(max_consecutive_losses=2, cooldown_sec=100)
    assert cd.can_trade(0)
    cd.on_trade_close(pnl=-1.0, now_ts=10)
    assert cd.can_trade(10)
    cd.on_trade_close(pnl=-0.5, now_ts=20)
    assert not cd.can_trade(25)
    assert cd.can_trade(120)

