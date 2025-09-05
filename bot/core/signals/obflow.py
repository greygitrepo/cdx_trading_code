"""OB-Flow v2: Pattern-based signal engine.

Patterns:
  A. Bid wall bounce
  B. Ask wall break
  C. Absorption then reversal
  D. Sweep then mean-revert
"""
from __future__ import annotations

"""OB-Flow v2: Pattern-based signal engine.

Patterns:
  A. Bid wall bounce
  B. Ask wall break
  C. Absorption then reversal
  D. Sweep then mean-revert
"""

from dataclasses import dataclass
from typing import Optional, Literal, Dict, Any

from bot.core.book import L2Book
from bot.core.features import basic_snapshot

Side = Literal["BUY", "SELL"]


@dataclass
class OBFlowConfig:
    wall_mult_min: float = 6.0
    depth_imb_L5_min: float = 0.18
    tps_min_breakout: float = 8.0


def decide(book: L2Book, cfg: OBFlowConfig) -> Optional[Dict[str, Any]]:
    feat = basic_snapshot(book)
    # Simplified A/B triggers using top-level features
    # A: bid wall bounce proxy (imbalance high and micro > mid)
    if feat["imb_l5"] >= cfg.depth_imb_L5_min and feat["micro"] > feat["mid"]:
        return {
            "type": "A",
            "side": "BUY",
            "score": float(min(1.0, max(0.0, feat["imb_l5"]))),
            "reason": "imbalance_high_micro_above_mid",
            "features": feat,
        }
    # B: ask wall break proxy (micro above mid and spread small)
    if feat["micro"] > feat["mid"] and feat["spread"] <= max(0.0, feat["mid"] * 0.0008):
        return {
            "type": "B",
            "side": "BUY",
            "score": 0.5,
            "reason": "micro_above_mid_spread_tight",
            "features": feat,
        }
    # C/D placeholders
    return None
