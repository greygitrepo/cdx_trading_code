"""OB-Flow v2: Simple risk helpers (TP/SL/time stop placeholders)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

@dataclass
class RiskConfig:
    tp_pct: float = 0.0045
    sl_pct: float = 0.0035
    time_stop_sec: int = 5


def compute_tp_sl(entry_price: float, side: str, cfg: RiskConfig) -> Tuple[float, float]:
    if side.upper() == "BUY":
        return entry_price * (1 + cfg.tp_pct), entry_price * (1 - cfg.sl_pct)
    return entry_price * (1 - cfg.tp_pct), entry_price * (1 + cfg.sl_pct)
