from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set
import time


@dataclass
class Slot:
    symbol: str
    state: str = "ENTRY"  # ENTRY -> MANAGED -> CLOSED
    budget_usdt: float = 0.0
    entry_time: float = field(default_factory=time.time)

    def set_budget(self, v: float) -> None:
        self.budget_usdt = float(v)

    def set_state(self, st: str) -> None:
        self.state = st


class SlotManager:
    def __init__(self, max_slots: int) -> None:
        self.max_slots = max_slots
        self._slots: Dict[int, Optional[Slot]] = {i: None for i in range(max_slots)}

    def acquire(self, symbol: str) -> Slot:
        if symbol in self.current_symbols():
            raise ValueError("symbol already acquired")
        for i in range(self.max_slots):
            if self._slots[i] is None:
                s = Slot(symbol=symbol)
                self._slots[i] = s
                return s
        raise RuntimeError("no free slot")

    def release(self, symbol: str) -> None:
        for i, v in self._slots.items():
            if v is not None and v.symbol == symbol:
                self._slots[i] = None
                return

    def get_slot(self, symbol: str) -> Slot:
        for v in self._slots.values():
            if v is not None and v.symbol == symbol:
                return v
        raise KeyError(symbol)

    def current_symbols(self) -> Set[str]:
        return {v.symbol for v in self._slots.values() if v is not None}

    def active_count(self) -> int:
        return sum(1 for v in self._slots.values() if v is not None)

    def free_count(self) -> int:
        return sum(1 for v in self._slots.values() if v is None)
