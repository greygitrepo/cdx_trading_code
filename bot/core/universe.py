"""Universe selection logic based on simple metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class SymbolMetrics:
    symbol: str
    spread_mult: float
    depth_usd: float
    vol_rank: int


def select_universe(items: List[SymbolMetrics], topN: int, spread_max_mult: float, min_depth_usd: float) -> list[str]:
    filtered = [x for x in items if x.spread_mult <= spread_max_mult and x.depth_usd >= min_depth_usd]
    filtered.sort(key=lambda x: x.vol_rank)
    return [x.symbol for x in filtered[:topN]]

