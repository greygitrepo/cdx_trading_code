"""OB-Flow v2: Minimal position state tracking."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class PositionState:
    symbol: str
    side: Optional[str] = None
    qty: float = 0.0

    def is_flat(self) -> bool:
        return not self.side or self.qty == 0.0

    def enter(self, side: str, qty: float) -> None:
        self.side = side.upper()
        self.qty = float(qty)

    def exit_all(self) -> None:
        self.side = None
        self.qty = 0.0
