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
    bb = book.best_bid()
    ba = book.best_ask()
    if not bb or not ba:
        return 0.0
    vb = max(bb[1], 0.0)
    va = max(ba[1], 0.0)
    den = (vb + va) or 1.0
    return (vb - va) / den

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
    return {
        "mid": mid,
        "spread": spr,
        "micro": microprice(book),
        "imb_l5": depth_imbalance(book, 5),
    }
