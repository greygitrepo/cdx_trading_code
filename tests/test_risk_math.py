import math
from bot.core.risk_math import Fees, net_pnl, tp_sl_trigger


def test_net_pnl_with_fees():
    fees = Fees(taker_bps=5.5, maker_bps=2.0)
    pnl = net_pnl(100.0, 110.0, 1.0, fees)
    assert math.isclose(pnl, 9.8845, rel_tol=1e-5)


def test_tp_sl_trigger_boundaries():
    cfg = {"risk": {"tp_pct": 0.05, "sl_pct": 0.02}}
    pos = {"entry_px": 100.0, "qty": 1.0}
    md_tp = {"payload": {"mid": 105.0}}
    md_sl = {"payload": {"mid": 98.0}}
    assert tp_sl_trigger(pos, md_tp, cfg) == {"should_exit": True, "reason": "tp"}
    assert tp_sl_trigger(pos, md_sl, cfg) == {"should_exit": True, "reason": "sl"}
