"""Strategy pack MIS/VRS/LSR: compute signals and scores.

This is a simplified, testable implementation mirroring the spec logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .indicators import ema, rsi2, vwap_deviation
from .types import Side


@dataclass
class StrategyParams:
    ema_fast: int = 3
    ema_slow: int = 9
    adx_len: int = 7  # placeholder: not used in simplified test
    vwap_dev_for_vrs: float = 0.0035
    rsi2_low: int = 4
    rsi2_high: int = 96


def mis_signal(closes: list[float], orderbook_imbalance: float, spread: float, spread_threshold: float,
               params: StrategyParams) -> Tuple[Optional[Side], float]:
    if len(closes) < 3:
        return None, 0.0
    efast = ema(closes, params.ema_fast)
    eslow = ema(closes, params.ema_slow)
    score = 0.0
    side: Optional[Side] = None
    if efast > eslow and orderbook_imbalance >= 0.60 and spread <= spread_threshold:
        side = Side.BUY
        score = min(1.0, (efast - eslow) / max(1e-9, eslow) + orderbook_imbalance - 0.59)
    elif efast < eslow and orderbook_imbalance <= 0.40 and spread <= spread_threshold:
        side = Side.SELL
        score = min(1.0, (eslow - efast) / max(1e-9, eslow) + (0.41 - orderbook_imbalance))
    return side, score


def vrs_signal(closes: list[float], volumes: list[float], params: StrategyParams) -> Tuple[Optional[Side], float]:
    dev = vwap_deviation(closes, volumes)
    r = rsi2(closes)
    # Prioritize deviation side, then fall back to RSI extremes
    if dev >= params.vwap_dev_for_vrs:
        return Side.BUY, min(1.0, dev / params.vwap_dev_for_vrs)
    if dev <= -params.vwap_dev_for_vrs:
        return Side.SELL, min(1.0, abs(dev) / params.vwap_dev_for_vrs)
    if r <= params.rsi2_low:
        return Side.BUY, 0.5
    if r >= (100 - params.rsi2_low):
        return Side.SELL, 0.5
    return None, 0.0


def lsr_signal(wick_long: bool, trade_burst: bool, oi_drop: bool) -> Tuple[Optional[Side], float]:
    if trade_burst and oi_drop and wick_long:
        return Side.SELL, 1.0
    if trade_burst and oi_drop and not wick_long:
        return Side.BUY, 1.0
    return None, 0.0


def select_strategy(mis: Tuple[Optional[Side], float], vrs: Tuple[Optional[Side], float], lsr: Tuple[Optional[Side], float]) -> Tuple[Optional[str], Optional[Side]]:
    choices = []
    if mis[0] is not None:
        choices.append(("MIS", mis[1], mis[0]))
    if vrs[0] is not None:
        choices.append(("VRS", vrs[1], vrs[0]))
    if lsr[0] is not None:
        choices.append(("LSR", lsr[1], lsr[0]))
    if not choices:
        return None, None
    choices.sort(key=lambda x: x[1], reverse=True)
    name, _, side = choices[0]
    return name, side
