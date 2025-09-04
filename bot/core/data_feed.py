"""Data feed scaffolding for Bybit v5 public streams (offline-testable).

This module exposes small utilities for backoff and a generic event stream adapter
that can later be wired to WebSocket. For Phase 2 tests, we simulate WS messages
using in-memory generators.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generator, Iterable, Iterator


def exp_backoff(initial: float = 0.2, maximum: float = 10.0) -> Iterator[float]:
    delay = initial
    while True:
        yield delay
        delay = min(maximum, delay * 2)


@dataclass
class StreamAdapter:
    """Adapt an iterable/generator as a stream of events."""

    source: Callable[[], Iterable[dict]]

    def __iter__(self) -> Iterator[dict]:  # pragma: no cover - trivial
        yield from self.source()


def make_generator(events: list[dict]) -> Callable[[], Iterable[dict]]:
    def _gen() -> Generator[dict, None, None]:
        for ev in events:
            yield ev

    return _gen
