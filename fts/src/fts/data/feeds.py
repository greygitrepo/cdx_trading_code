import os
from typing import Iterator

from .simulator import Simulator
from ..common.types import Event


class UnifiedFeed(Iterator[Event]):
    """Yield events from live exchange or simulator."""

    def __init__(self, seed: int = 0):
        if os.getenv("BYBIT_API_KEY"):
            raise RuntimeError(
                "Live feed not implemented; set BYBIT_API_KEY to use simulator"
            )
        self.sim = Simulator(seed=seed)

    def __iter__(self) -> "UnifiedFeed":
        return self

    def __next__(self) -> Event:
        return next(self.sim)
