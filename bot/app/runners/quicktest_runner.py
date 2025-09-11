"""Quick-test runner: short OB-Flow loop on TESTNET with aggressive params.

Extracted from bot/scripts/run_quicktest.py to improve readability.
"""

from __future__ import annotations
import os
import time
from pathlib import Path

from bot.core.exchange.bybit_v5 import BybitV5Client
from bot.core.book import L2Book
from bot.core.feed import Feed, FeedConfig
from bot.core.features import basic_snapshot
from bot.core.recorder import Recorder
from bot.core.signals.router import route


class QuickTestRunner:
    def __init__(self, out_path: Path | None = None) -> None:
        self.out_path = out_path or Path("logs/obflow_quick/events.jsonl")

    def run(self, *, symbol: str = "BTCUSDT", ticks: int = 100) -> Path:
        os.environ.setdefault("TESTNET", "true")
        os.environ.setdefault("LIVE_MODE", "true")
        os.environ.setdefault("STUB_MODE", "false")
        rec = Recorder(self.out_path)
        feed = Feed(FeedConfig(symbol=symbol, depth=1))
        _client = BybitV5Client(testnet=True, category="linear")
        book = L2Book(symbol=symbol)
        n = 0
        for ev in feed.orderbook():
            if ev.get("type") == "snapshot":
                book.seq = ev.get("seq", 0)
            elif ev.get("type") == "delta":
                book.seq = ev.get("seq", book.seq + 1)
            feat = basic_snapshot(book)
            sig = route(book)
            rec.write({"type": "feature", "symbol": symbol, **feat})
            if sig:
                rec.write({"type": "signal", "symbol": symbol, **sig})
            n += 1
            if n >= ticks:
                break
            time.sleep(0.01)
        return self.out_path
