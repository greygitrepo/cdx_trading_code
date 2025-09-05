from __future__ import annotations

from bot.core.book import L2Book
from bot.core.queue import estimate_queue_fraction_l1


def test_estimate_queue_fraction_l1() -> None:
    b = L2Book(symbol="BTCUSDT")
    b.bids[100.0] = 5.0
    b.asks[100.1] = 3.0
    frac, l1 = estimate_queue_fraction_l1(b, side="BUY", my_qty=1.0)
    assert 0.0 < frac <= 1.0
    assert abs(l1 - 5.0) < 1e-9
    frac2, _ = estimate_queue_fraction_l1(b, side="SELL", my_qty=10.0)
    assert abs(frac2 - 1.0) < 1e-9

