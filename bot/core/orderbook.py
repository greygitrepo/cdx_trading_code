"""Orderbook snapshot-diff synchronization helpers for Bybit v5 public feeds.

This module is offline-testable; it does not require network. It provides
pure functions/classes to maintain book state using snapshot and delta events
with sequence verification and a resnapshot signal when a gap is detected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Literal, Tuple

Side = Literal["bids", "asks"]


@dataclass(slots=True)
class L2Book:
    symbol: str
    seq: int = 0
    ts: int = 0
    bids: Dict[float, float] = field(default_factory=dict)
    asks: Dict[float, float] = field(default_factory=dict)

    def best_bid(self) -> Tuple[float, float] | None:
        if not self.bids:
            return None
        p = max(self.bids.keys())
        return p, self.bids[p]

    def best_ask(self) -> Tuple[float, float] | None:
        if not self.asks:
            return None
        p = min(self.asks.keys())
        return p, self.asks[p]

    def copy_levels(self) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        return (sorted(self.bids.items(), key=lambda x: (-x[0], x[1])),
                sorted(self.asks.items(), key=lambda x: (x[0], x[1])))


def _apply_side(levels: Dict[float, float], updates: Iterable[Tuple[float, float]]) -> None:
    for price, size in updates:
        if size == 0.0:
            levels.pop(price, None)
        else:
            levels[price] = size


def apply_snapshot(book: L2Book, seq: int, ts: int,
                   bids: Iterable[Tuple[float, float]],
                   asks: Iterable[Tuple[float, float]]) -> None:
    book.seq = seq
    book.ts = ts
    book.bids.clear()
    book.asks.clear()
    _apply_side(book.bids, bids)
    _apply_side(book.asks, asks)


def apply_delta(book: L2Book, seq: int, ts: int,
                bids: Iterable[Tuple[float, float]],
                asks: Iterable[Tuple[float, float]]) -> bool:
    """Apply delta with sequence verification.

    Returns True if applied, False if sequence gap detected (caller should resnapshot).
    """
    if book.seq and seq != book.seq + 1:
        return False
    _apply_side(book.bids, bids)
    _apply_side(book.asks, asks)
    book.seq = seq
    book.ts = ts
    return True


def process_stream(book: L2Book, events: Iterable[dict]) -> Tuple[L2Book, int]:
    """Process a mixed stream of snapshot/delta events.

    Event schema (simplified, testable offline):
    - {"type": "snapshot", "seq": int, "ts": int, "bids": [[p,s], ...], "asks": [[p,s], ...]}
    - {"type": "delta",    "seq": int, "ts": int, "bids": [[p,s], ...], "asks": [[p,s], ...]}

    Returns (book, resnapshot_count)
    """
    resnap = 0
    for ev in events:
        if ev["type"] == "snapshot":
            apply_snapshot(book, ev["seq"], ev["ts"], _pairs(ev.get("bids", [])), _pairs(ev.get("asks", [])))
        elif ev["type"] == "delta":
            ok = apply_delta(book, ev["seq"], ev["ts"], _pairs(ev.get("bids", [])), _pairs(ev.get("asks", [])))
            if not ok:
                resnap += 1
                # Expect a snapshot soon after; in test, we simply skip until next snapshot
    return book, resnap


def _pairs(arr: Iterable[Iterable[float]]) -> List[Tuple[float, float]]:
    return [(float(p), float(s)) for p, s in arr]

