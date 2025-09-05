from __future__ import annotations

from bot.core.book import L2Book
from bot.core.features import mid_spread, microprice, depth_imbalance


def test_basic_features_top_of_book():
    b = L2Book(symbol="BTCUSDT")
    # Seed best bid/ask
    b.bids[100.0] = 2.0
    b.asks[100.2] = 1.0
    mid, spr = mid_spread(b)
    assert abs(mid - 100.1) < 1e-9
    assert abs(spr - 0.2) < 1e-9
    micro = microprice(b)
    # Micro closer to ask due to smaller ask size
    assert 100.1 < micro <= 100.2
    imb = depth_imbalance(b, 5)
    assert imb > 0

