"""OB-Flow v2: Feature computation on L2 book and simple ticks.

Implements core features used by OB-Flow patterns at low latency.
"""
from __future__ import annotations

from typing import Dict, Tuple
from .book import L2Book

def mid_spread(book: L2Book) -> Tuple[float, float]:
    bb = book.best_bid()
    ba = book.best_ask()
    if not bb or not ba:
        return 0.0, 0.0
    mid = (bb[0] + ba[0]) / 2.0
    spr = max(0.0, ba[0] - bb[0])
    return mid, spr

def microprice(book: L2Book) -> float:
    bb = book.best_bid()
    ba = book.best_ask()
    if not bb or not ba:
        return 0.0
    pb, vb = bb
    pa, va = ba
    den = vb + va
    if den <= 0:
        return (pb + pa) / 2.0
    return (pa * vb + pb * va) / den

def depth_imbalance(book: L2Book, levels: int = 5) -> float:
    """Compute top-N depth imbalance using L2 levels.

    Returns (sum_bid_sizes - sum_ask_sizes) / (sum_bid_sizes + sum_ask_sizes).

    Falls back to 0.0 if either side has no liquidity or denominator is 0.
    """
    bids, asks = book.copy_levels()
    if not bids or not asks:
        return 0.0
    # Sum top-N by price priority
    sum_b = sum(max(sz, 0.0) for _, sz in bids[: max(1, int(levels))])
    sum_a = sum(max(sz, 0.0) for _, sz in asks[: max(1, int(levels))])
    den = sum_b + sum_a
    if den <= 0:
        return 0.0
    return (sum_b - sum_a) / den

def ofi_l1(
    prev_bb: Tuple[float, float] | None,
    prev_ba: Tuple[float, float] | None,
    cur_bb: Tuple[float, float] | None,
    cur_ba: Tuple[float, float] | None,
) -> float:
    ofi = 0.0
    if prev_bb and cur_bb:
        if cur_bb[0] > prev_bb[0]:
            ofi += cur_bb[1]
        elif cur_bb[0] < prev_bb[0]:
            ofi -= prev_bb[1]
    if prev_ba and cur_ba:
        if cur_ba[0] < prev_ba[0]:
            ofi += cur_ba[1]
        elif cur_ba[0] > prev_ba[0]:
            ofi -= prev_ba[1]
    return ofi

def basic_snapshot(book: L2Book) -> Dict[str, float]:
    mid, spr = mid_spread(book)
    feat: Dict[str, float] = {
        "mid": mid,
        "spread": spr,
        "micro": microprice(book),
        "imb_l5": depth_imbalance(book, 5),
    }
    # Allow callers to inject additional lightweight features (e.g., TPS)
    extra = getattr(book, "extra_features", None)
    if isinstance(extra, dict):
        try:
            feat.update({k: float(v) for k, v in extra.items()})
        except Exception:
            pass
    return feat
