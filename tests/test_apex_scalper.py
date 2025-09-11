import pytest

from bot.core.signals.apex_scalper import (
    APEXConfig,
    decide_apex,
    decide_regime,
)
from bot.core.apex_executor import build_entry_from_signal, build_reduce_only


pytestmark = pytest.mark.strategy


def test_regime_switching_simple():
    cfg = APEXConfig()
    assert decide_regime(adx14=10, rv_15m_pct=1.0, vol_spike_mult=1.0, cfg=cfg) == "A"
    assert decide_regime(adx14=30, rv_15m_pct=1.0, vol_spike_mult=1.0, cfg=cfg) == "B"
    assert decide_regime(adx14=10, rv_15m_pct=1.0, vol_spike_mult=2.0, cfg=cfg) == "B"


def test_vwap_reversion_entry_and_trail_params():
    cfg = APEXConfig()
    ctx = {
        "adx14": 10.0,
        "rv_15m_pct": 1.0,
        "vol_spike_mult": 1.0,
        "rsi2": 5.0,
        "bb_touch": True,
        "vwap_dev_pct": -0.004,  # -0.4%
        "ob_bid_w": 0.60,
    }
    sig = decide_apex(ctx, cfg)
    assert sig and sig["play"] == "VWAP" and sig["side"] == "BUY" and sig["regime"] == "A"
    # executor
    plan = build_entry_from_signal(signal=sig, last_mid=100.0, qty=1.0, post_only_ttl_sec=cfg.strategy_A.entry_ttl_sec)
    assert plan.tif == "PostOnly" and plan.type == "Limit" and plan.ttl_sec == cfg.strategy_A.entry_ttl_sec


def test_momentum_breakout_entry_and_slip_guard_flag():
    cfg = APEXConfig()
    ctx = {
        "adx14": 25.0,
        "rv_15m_pct": 1.0,
        "vol_spike_mult": cfg.regime.vol_spike_mult,
        "ema_fast": 101.0,
        "ema_slow": 100.0,
        "above_vwap": True,
        "ob_bid_w": 0.60,
        "abuy_share_10s": 0.70,
        "ret1m_pct": 0.002,
    }
    sig = decide_apex(ctx, cfg)
    assert sig and sig["play"] == "MOMO" and sig["regime"] == "B"
    plan = build_entry_from_signal(signal=sig, last_mid=100.0, qty=1.0)
    # momentum defaults to taker IOC
    assert plan.tif == "IOC" and plan.type in {"IOC", "Market", "Limit"}


def test_reduce_only_and_ttl():
    ro = build_reduce_only(side="SELL", qty=0.5, price=101.0, post_only=True, ttl_sec=20)
    assert ro.reduce_only and ro.tif == "PostOnly" and ro.ttl_sec == 20
