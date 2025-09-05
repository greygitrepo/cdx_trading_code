"""Heuristics for queue position approximation at best bid/ask.

These are rough estimates using only L1 sizes suitable for backtests without
full market-by-order data.
"""
from __future__ import annotations

from typing import Literal, Tuple

from .book import L2Book

Side = Literal["BUY", "SELL"]


def estimate_queue_fraction_l1(book: L2Book, side: Side, my_qty: float) -> Tuple[float, float]:
    """Estimate the fraction of the visible L1 queue our order would occupy.

    Returns (fraction, l1_size). If no L1, returns (1.0, 0.0) (worst case).
    """
    level = book.best_bid() if side == "BUY" else book.best_ask()
    if not level:
        return 1.0, 0.0
    _, size = level
    size = max(0.0, float(size))
    if size <= 0.0:
        return 1.0, 0.0
    frac = min(1.0, max(0.0, my_qty) / size)
    return frac, size

