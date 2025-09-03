"""WS snapshot-delta and reconnection behavior (STUB mode)."""

from __future__ import annotations

from bot.core.data_ws import PublicWS


def test_stub_orderbook_replay_and_gap_recovery() -> None:
    ws = PublicWS(symbol="BTCUSDT", depth=1)
    book, resnap = ws.replay_orderbook()
    assert resnap >= 1
    assert book.seq == 10
    assert book.best_bid() == (101.0, 3.0)
    assert book.best_ask() == (101.2, 1.0)

