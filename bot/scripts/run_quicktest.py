"""Run OB-Flow quicktest loop on TESTNET with aggressive params."""
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


def main() -> None:
    # Safety/env
    os.environ.setdefault("TESTNET", "true")
    os.environ.setdefault("LIVE_MODE", "true")
    os.environ.setdefault("STUB_MODE", "false")
    sym = os.environ.get("BYBIT_SYMBOL", "BTCUSDT")
    rec = Recorder(Path("logs/obflow_quick/events.jsonl"))
    feed = Feed(FeedConfig(symbol=sym, depth=1))
    _client = BybitV5Client(testnet=True, category="linear")
    book = L2Book(symbol=sym)

    ticks = 0
    for ev in feed.orderbook():
        # For simplicity, assume stream contains snapshot/delta and book.seq advances
        if ev.get("type") == "snapshot":
            book.seq = ev.get("seq", 0)
        elif ev.get("type") == "delta":
            book.seq = ev.get("seq", book.seq + 1)
        feat = basic_snapshot(book)
        sig = route(book)
        rec.write({"type": "feature", "symbol": sym, **feat})
        if sig:
            rec.write({"type": "signal", "symbol": sym, **sig})
        ticks += 1
        if ticks >= 100:  # short loop for smoke
            break
        time.sleep(0.01)


if __name__ == "__main__":
    main()
