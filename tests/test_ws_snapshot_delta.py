"""WS snapshot-delta and reconnection behavior (STUB mode)."""

from __future__ import annotations

import pytest
from bot.core.data_ws import PublicWS


@pytest.mark.unit
def test_stub_orderbook_replay_and_gap_recovery(monkeypatch) -> None:
    # Force stub mode to use local JSONL replay regardless of env
    monkeypatch.setenv("STUB_MODE", "true")
    monkeypatch.setenv("LIVE_MODE", "false")
    monkeypatch.setenv("TESTNET", "false")
    ws = PublicWS(symbol="BTCUSDT", depth=1)
    book, resnap = ws.replay_orderbook()
    assert resnap >= 1
    assert book.seq == 10
    assert book.best_bid() == (101.0, 3.0)
    assert book.best_ask() == (101.2, 1.0)
