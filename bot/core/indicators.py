"""Lightweight indicators used by strategy signals (offline-testable)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, List


def ema(values: Iterable[float], period: int) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    k = 2 / (period + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi2(closes: Iterable[float]) -> float:
    vals = list(closes)[-3:]
    if len(vals) < 3:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    if gains + losses == 0:
        return 50.0
    rs = gains / max(1e-12, losses)
    return 100 - (100 / (1 + rs))


def vwap_deviation(prices: Iterable[float], volumes: Iterable[float]) -> float:
    ps = list(prices)
    vs = list(volumes)
    if not ps or not vs or len(ps) != len(vs):
        return 0.0
    pv = sum(p * v for p, v in zip(ps, vs))
    v = sum(vs)
    if v == 0:
        return 0.0
    vwap = pv / v
    last = ps[-1]
    return (last - vwap) / vwap


@dataclass
class Rolling:
    maxlen: int
    values: Deque[float] = field(default_factory=deque)

    def add(self, v: float) -> None:
        if not self.values:
            self.values = deque([v], maxlen=self.maxlen)
        elif self.values.maxlen != self.maxlen:
            self.values = deque(self.values, maxlen=self.maxlen)
            self.values.append(v)
        else:
            self.values.append(v)

    def list(self) -> List[float]:  # pragma: no cover - trivial
        return list(self.values)
