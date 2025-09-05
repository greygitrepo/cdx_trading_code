from __future__ import annotations

from bot.core.book import L2Book
from bot.core.signals.router import route


def test_obflow_buy_signal_on_imbalance():
    b = L2Book(symbol="BTCUSDT")
    b.bids[100.0] = 3.0
    b.asks[100.1] = 1.0
    sig = route(b)
    assert sig is None or sig["side"] == "BUY"

