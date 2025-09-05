"""OB-Flow v2: Pattern-based signal engine.

Patterns:
  A. Bid wall bounce
  B. Ask wall break
  C. Absorption then reversal
  D. Sweep then mean-revert
"""
from __future__ import annotations


from dataclasses import dataclass
from typing import Optional, Literal, Dict, Any

from bot.core.book import L2Book
from bot.core.features import basic_snapshot

Side = Literal["BUY", "SELL"]


@dataclass
class OBFlowConfig:
    """Thresholds for OB-Flow patterns.

    Mirrors fields in ParamsPack.obflow to allow YAML linkage while keeping a
    lightweight dataclass in the signals module.
    """

    depth_imb_L5_min: float = 0.18
    spread_tight_mult_mid: float = 0.0008
    tps_min_breakout: float = 8.0
    c_absorption_min: float = 0.35
    d_wide_spread_mult_mid: float = 0.0015
    d_micro_dev_mult_spread: float = 0.40

    @staticmethod
    def from_params(params: "bot.configs.schemas.ParamsPack") -> "OBFlowConfig":  # type: ignore[name-defined]
        p = getattr(params, "obflow", None)
        if p is None:
            return OBFlowConfig()
        return OBFlowConfig(
            depth_imb_L5_min=float(getattr(p, "depth_imb_L5_min", 0.18)),
            spread_tight_mult_mid=float(getattr(p, "spread_tight_mult_mid", 0.0008)),
            tps_min_breakout=float(getattr(p, "tps_min_breakout", 8.0)),
            c_absorption_min=float(getattr(p, "c_absorption_min", 0.35)),
            d_wide_spread_mult_mid=float(getattr(p, "d_wide_spread_mult_mid", 0.0015)),
            d_micro_dev_mult_spread=float(getattr(p, "d_micro_dev_mult_spread", 0.40)),
        )


def decide(book: L2Book, cfg: OBFlowConfig) -> Optional[Dict[str, Any]]:
    feat = basic_snapshot(book)
    mid = feat.get("mid", 0.0)
    spr = feat.get("spread", 0.0)
    mic = feat.get("micro", 0.0)
    imb = feat.get("imb_l5", 0.0)

    # Pattern A: Bid/Ask wall bounce (contrarian micro tilt with strong top imbalance)
    if imb >= cfg.depth_imb_L5_min and mic > mid:
        return {
            "type": "A",
            "side": "BUY",
            "score": float(min(1.0, max(0.0, abs(imb)))),
            "reason": "bid_imbalance_high_micro_above_mid",
            "features": feat,
        }
    if imb <= -cfg.depth_imb_L5_min and mic < mid:
        return {
            "type": "A",
            "side": "SELL",
            "score": float(min(1.0, max(0.0, abs(imb)))),
            "reason": "ask_imbalance_high_micro_below_mid",
            "features": feat,
        }

    # Pattern B: Wall break (micro tilt and tight spread)
    tight = spr <= max(0.0, mid * cfg.spread_tight_mult_mid)
    if tight and mic > mid:
        return {
            "type": "B",
            "side": "BUY",
            "score": 0.5,
            "reason": "micro_above_mid_spread_tight",
            "features": feat,
        }
    if tight and mic < mid:
        return {
            "type": "B",
            "side": "SELL",
            "score": 0.5,
            "reason": "micro_below_mid_spread_tight",
            "features": feat,
        }

    # Pattern C: Absorption then reversal (proxy: strong imbalance opposite to micro tilt)
    if abs(imb) >= cfg.c_absorption_min:
        if imb > 0 and mic < mid:
            return {
                "type": "C",
                "side": "SELL",
                "score": float(min(1.0, abs(imb))),
                "reason": "bid_absorption_reversal_down",
                "features": feat,
            }
        if imb < 0 and mic > mid:
            return {
                "type": "C",
                "side": "BUY",
                "score": float(min(1.0, abs(imb))),
                "reason": "ask_absorption_reversal_up",
                "features": feat,
            }

    # Pattern D: Sweep then mean-revert (proxy: wide spread and micro far from mid → fade)
    if mid > 0 and spr >= mid * cfg.d_wide_spread_mult_mid:
        # Measure micro deviation relative to spread to avoid tick-size issues
        dev = abs(mic - mid) / (spr or 1.0)
        if dev >= cfg.d_micro_dev_mult_spread:
            side: Side = "SELL" if mic > mid else "BUY"
            return {
                "type": "D",
                "side": side,
                "score": float(min(1.0, dev)),
                "reason": "wide_spread_micro_extreme_mean_revert",
                "features": feat,
            }

    return None
