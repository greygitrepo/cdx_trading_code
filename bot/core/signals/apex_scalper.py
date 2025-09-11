"""APEX Scalper: regime switching VWAP reversion / momentum breakout.

This module provides a small, test-friendly subset of the full strategy so it can
be unit-tested offline. It does not depend on exchange clients. Real-time
integration (order placement, TTL/repricing, trade_state updates) is handled by
the runner/executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class _ScannerCfg:
    top_n: int = 10
    min_15m_turnover_usd: float = 50_000_000
    max_spread_pct: float = 0.03
    rv_15m_pct_range: Tuple[float, float] = (0.6, 2.5)
    min_depth_usd_l10: float = 300_000


@dataclass
class _RegimeCfg:
    adx_len: int = 14
    adx_trend_threshold: float = 18.0
    vol_spike_mult: float = 1.8


@dataclass
class _StrA:
    rsi_len: int = 2
    rsi_buy: float = 8.0
    bb_len: int = 20
    bb_std: float = 2.2
    vwap_dev_buy_pct: float = -0.35
    ob_bid_min: float = 0.53
    entry_ttl_sec: int = 20
    tp1_pct: float = 0.20
    tp1_size: float = 0.60
    tp2_pct: float = 0.35
    tp2_size: float = 0.40
    sl_pct: float = 0.25
    atr_k_sl: float = 1.3
    trail_activate_pct: float = 0.25
    trail_gap_pct: float = 0.15
    time_stop_sec: int = 180


@dataclass
class _StrB:
    ema_fast: int = 9
    ema_slow: int = 21
    above_vwap: bool = True
    ret1m_min_pct: float = 0.12
    ret1m_max_pct: float = 0.60
    ob_bid_min: float = 0.56
    abuy_share_10s_min: float = 0.60
    taker_entry: bool = True
    entry_slip_guard_pct: float = 0.08
    tp1_pct: float = 0.40
    tp1_size: float = 0.40
    tp2_pct: float = 0.60
    tp2_size: float = 0.60
    sl_pct: float = 0.30
    atr_k_sl: float = 1.0
    trail_after_tp1_pct: float = 0.20
    tp_postonly_ttl_sec: int = 20
    time_stop_sec: int = 90


@dataclass
class APEXConfig:
    """Top-level config bound from YAML: params.apex.*"""

    scanner: _ScannerCfg = _ScannerCfg()
    regime: _RegimeCfg = _RegimeCfg()
    strategy_A: _StrA = _StrA()
    strategy_B: _StrB = _StrB()

    @staticmethod
    def from_params(params: Any) -> "APEXConfig":
        apx = getattr(params, "apex", None)
        if apx is None:
            return APEXConfig()

        def _ld(obj: Any, dto):
            d = {}
            for k in dto.__dataclass_fields__.keys():  # type: ignore[attr-defined]
                if hasattr(obj, k):
                    d[k] = getattr(obj, k)
            return type(dto)(**d)  # same dataclass type

        scanner = _ld(getattr(apx, "scanner", _ScannerCfg()), _ScannerCfg())
        regime = _ld(getattr(apx, "regime", _RegimeCfg()), _RegimeCfg())
        stra = _ld(getattr(apx, "strategy_A", _StrA()), _StrA())
        strb = _ld(getattr(apx, "strategy_B", _StrB()), _StrB())
        return APEXConfig(scanner=scanner, regime=regime, strategy_A=stra, strategy_B=strb)


def decide_regime(*, adx14: float, rv_15m_pct: float, vol_spike_mult: float, cfg: APEXConfig) -> str:
    """Return 'A' (range/VWAP) or 'B' (trend/momentum) based on thresholds.

    - A: ADX < threshold AND rv in [low, high]
    - B: ADX >= threshold OR vol spike >= cfg.regime.vol_spike_mult
    """
    low, high = cfg.regime.rv_15m_pct_range if hasattr(cfg.regime, "rv_15m_pct_range") else (0.6, 2.5)
    if (adx14 >= cfg.regime.adx_trend_threshold) or (vol_spike_mult >= cfg.regime.vol_spike_mult):
        return "B"
    if (adx14 < cfg.regime.adx_trend_threshold) and (low <= rv_15m_pct <= high):
        return "A"
    # Default to A when ambiguous but within band
    return "A" if rv_15m_pct <= high else "B"


def signal_vwap_reversion(*, rsi2: float, bb_touch: bool, vwap_dev_pct: float, ob_bid_w: float, cfg: APEXConfig) -> Optional[Dict[str, Any]]:
    """Return a long VWAP reversion signal if conditions are met.

    Minimal, test-oriented criteria only. The executor handles actual order details.
    """
    a = cfg.strategy_A
    if (
        rsi2 <= a.rsi_buy
        and bb_touch
        and vwap_dev_pct <= a.vwap_dev_buy_pct / 100.0  # config is in pct terms
        and ob_bid_w >= a.ob_bid_min
    ):
        return {
            "play": "VWAP",
            "side": "BUY",
            "tp1_pct": a.tp1_pct / 100.0,
            "tp2_pct": a.tp2_pct / 100.0,
            "sl_pct": a.sl_pct / 100.0,
            "trail_activate_pct": a.trail_activate_pct / 100.0,
            "trail_gap_pct": a.trail_gap_pct / 100.0,
            "time_stop_sec": a.time_stop_sec,
        }
    return None


def signal_momentum_breakout(
    *,
    ema_fast: float,
    ema_slow: float,
    above_vwap: bool,
    vol_spike_mult: float,
    ob_bid_w: float,
    abuy_share_10s: float,
    ret1m_pct: float,
    cfg: APEXConfig,
) -> Optional[Dict[str, Any]]:
    b = cfg.strategy_B
    if (
        (ema_fast > ema_slow)
        and (not b.above_vwap or above_vwap)
        and (vol_spike_mult >= cfg.regime.vol_spike_mult)
        and (ob_bid_w >= b.ob_bid_min)
        and (abuy_share_10s >= b.abuy_share_10s_min)
        and (b.ret1m_min_pct / 100.0) <= ret1m_pct <= (b.ret1m_max_pct / 100.0)
    ):
        return {
            "play": "MOMO",
            "side": "BUY",
            "taker_entry": bool(b.taker_entry),
            "tp1_pct": b.tp1_pct / 100.0,
            "tp2_pct": b.tp2_pct / 100.0,
            "sl_pct": b.sl_pct / 100.0,
            "trail_after_tp1_pct": b.trail_after_tp1_pct / 100.0,
            "entry_slip_guard_pct": b.entry_slip_guard_pct / 100.0,
            "time_stop_sec": b.time_stop_sec,
        }
    return None


def decide_apex(context: Dict[str, float], cfg: APEXConfig) -> Optional[Dict[str, Any]]:
    """High-level decision entry for runner unit tests.

    The `context` dictionary should provide:
    - adx14, rv_15m_pct, vol_spike_mult
    - rsi2, bb_touch(bool cast), vwap_dev_pct, ob_bid_w
    - ema_fast, ema_slow, above_vwap(bool cast), abuy_share_10s, ret1m_pct
    """
    regime = decide_regime(
        adx14=float(context.get("adx14", 0.0)),
        rv_15m_pct=float(context.get("rv_15m_pct", 0.0)),
        vol_spike_mult=float(context.get("vol_spike_mult", 0.0)),
        cfg=cfg,
    )
    if regime == "A":
        sig = signal_vwap_reversion(
            rsi2=float(context.get("rsi2", 100.0)),
            bb_touch=bool(context.get("bb_touch", False)),
            vwap_dev_pct=float(context.get("vwap_dev_pct", 0.0)),
            ob_bid_w=float(context.get("ob_bid_w", 0.0)),
            cfg=cfg,
        )
        if sig:
            sig["regime"] = "A"
            return sig
    else:
        sig = signal_momentum_breakout(
            ema_fast=float(context.get("ema_fast", 0.0)),
            ema_slow=float(context.get("ema_slow", 0.0)),
            above_vwap=bool(context.get("above_vwap", True)),
            vol_spike_mult=float(context.get("vol_spike_mult", 0.0)),
            ob_bid_w=float(context.get("ob_bid_w", 0.0)),
            abuy_share_10s=float(context.get("abuy_share_10s", 0.0)),
            ret1m_pct=float(context.get("ret1m_pct", 0.0)),
            cfg=cfg,
        )
        if sig:
            sig["regime"] = "B"
            return sig
    return None
