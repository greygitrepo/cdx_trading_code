import random
from typing import Iterator

from ..common.types import Event


class Simulator(Iterator[Event]):
    """Simple deterministic simulator generating events."""

    def __init__(self, seed: int = 0):
        random.seed(seed)
        self.step = 0
        self.anchor = 100.0

    def __iter__(self) -> "Simulator":
        return self

    def __next__(self) -> Event:
        self.step += 1
        phase = self.step % 4
        if phase == 0:
            price = self.anchor + 5
            micro = self.anchor - 1
            z_flow = 3.5
            depth_ratio = 0.3
            lambda_drop = 0.3
        elif phase == 2:
            price = self.anchor - 5
            micro = self.anchor + 1
            z_flow = 3.5
            depth_ratio = 0.3
            lambda_drop = 0.3
        else:
            price = self.anchor
            micro = self.anchor
            z_flow = 0.0
            depth_ratio = 1.0
            lambda_drop = 1.0
        return Event(
            price=price,
            microprice=micro,
            depth_ratio=depth_ratio,
            z_flow=z_flow,
            lambda_drop=lambda_drop,
            anchor=self.anchor,
        )
