"""APEX execution adapter: translate APEX signals into order specs.

This is a thin, test-friendly layer that returns dictionaries in a shape the
existing order router can adapt. Live runner wires TTL/repricing and the actual
router calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ExecPlan:
    side: str
    type: str  # Limit|Market
    tif: str   # GTC|IOC|PostOnly
    qty: float
    price: Optional[float]
    reduce_only: bool = False
    ttl_sec: Optional[int] = None


def build_entry_from_signal(*, signal: Dict[str, Any], last_mid: float, qty: float, post_only_ttl_sec: int | None = None) -> ExecPlan:
    """Create an entry plan honoring maker/taker preference and TTL.

    - VWAP: Maker PostOnly at best price (price provided by caller), ttl applied
    - MOMO: taker_entry decides IOC/Market; apply slip guard at runner side
    """
    side = str(signal.get("side", "BUY")).upper()
    play = str(signal.get("play", "VWAP")).upper()
    if play == "VWAP":
        return ExecPlan(side=side, type="Limit", tif="PostOnly", qty=qty, price=last_mid, reduce_only=False, ttl_sec=post_only_ttl_sec)
    # MOMO
    taker = bool(signal.get("taker_entry", True))
    if taker:
        return ExecPlan(side=side, type="Market", tif="IOC", qty=qty, price=None, reduce_only=False, ttl_sec=None)
    return ExecPlan(side=side, type="Limit", tif="IOC", qty=qty, price=last_mid, reduce_only=False, ttl_sec=None)


def build_reduce_only(*, side: str, qty: float, price: Optional[float] = None, post_only: bool = True, ttl_sec: Optional[int] = None) -> ExecPlan:
    tif = "PostOnly" if post_only else "GTC"
    return ExecPlan(side=side, type=("Limit" if price is not None else "Market"), tif=tif, qty=qty, price=price, reduce_only=True, ttl_sec=ttl_sec)

