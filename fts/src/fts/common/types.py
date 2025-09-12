from dataclasses import dataclass
from typing import Optional


@dataclass
class Event:
    price: float
    microprice: float
    depth_ratio: float
    z_flow: float
    lambda_drop: float
    anchor: float


@dataclass
class Signal:
    side: str
    tp_bps: int
    sl_bps: int
    mode: str = "TAKER"
    meta: Optional[dict] = None
