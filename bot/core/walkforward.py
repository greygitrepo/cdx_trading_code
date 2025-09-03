"""Walk-forward skeleton for parameter evaluation (placeholder)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple


@dataclass
class WFResult:
    segment: Tuple[int, int]
    pnl: float


def walkforward(segments: Iterable[Tuple[int, int]]) -> List[WFResult]:
    # Placeholder that returns zero PnL per segment
    return [WFResult(segment=s, pnl=0.0) for s in segments]

