from __future__ import annotations

from bot.strategies.obflow.strategy import OBFlowStrategy
from bot.strategies.obflow.config import OBFlowConfig
from bot.core.orderbook import L2Book, apply_snapshot


def _mk_book() -> L2Book:
    b = L2Book(symbol="BTCUSDT")
    apply_snapshot(
        b,
        seq=1,
        ts=1,
        bids=[(100.0, 10.0), (99.5, 5.0)],
        asks=[(100.5, 1.0), (101.0, 5.0)],
    )
    return b


def test_obflow_strategy_scores():
    s = OBFlowStrategy(OBFlowConfig(), None)
    book = _mk_book()
    score = s.score_tick(book)
    assert isinstance(score, float)
    # Ensure deterministic non-negative
    assert score >= 0.0

