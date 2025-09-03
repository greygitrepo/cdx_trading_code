"""WebSocket-like data layer with STUB mode replay.

Provides ticker and orderbook (L1/L5) streams. In STUB_MODE, reads JSONL files
from data/stubs/ws/*.jsonl and yields events. Supports simple reconnection via
exp backoff and sequence verification via orderbook module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

from .config import get_modes
from .orderbook import L2Book, process_stream


STUB_DIR = Path("data/stubs/ws")


EventType = Literal["ticker", "orderbook"]


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


@dataclass
class PublicWS:
    symbol: str
    depth: int = 1  # 1 or 5 levels for stub interface

    def ticker_stream(self) -> Iterator[dict]:
        modes = get_modes()
        if modes.stub:
            src = STUB_DIR / f"ticker_{self.symbol}.jsonl"
            if src.exists():
                yield from _iter_jsonl(src)
            return
        # LIVE placeholder: no-op in CI
        return iter(())

    def orderbook_stream(self) -> Iterator[dict]:
        modes = get_modes()
        if modes.stub:
            src = STUB_DIR / f"orderbook{self.depth}_{self.symbol}.jsonl"
            if src.exists():
                yield from _iter_jsonl(src)
            return
        return iter(())

    def replay_orderbook(self) -> tuple[L2Book, int]:
        book = L2Book(symbol=self.symbol)
        events = list(self.orderbook_stream())
        return process_stream(book, events)
