"""Orderbook snapshot-diff consistency and resnapshot handling tests."""

from __future__ import annotations

from bot.core.orderbook import L2Book, apply_snapshot, apply_delta, process_stream


def test_snapshot_then_deltas_consistent() -> None:
    book = L2Book(symbol="BTCUSDT")
    apply_snapshot(book, seq=1, ts=1000, bids=[(100.0, 1.0)], asks=[(100.1, 2.0)])
    ok = apply_delta(book, seq=2, ts=1001, bids=[(100.0, 1.5)], asks=[])
    assert ok is True
    ok = apply_delta(book, seq=3, ts=1002, bids=[(99.9, 1.0)], asks=[(100.1, 0.0)])
    assert ok is True
    # Best bid now 100.0 qty 1.5; ask removed at 100.1 -> no asks
    bb = book.best_bid()
    ba = book.best_ask()
    assert bb == (100.0, 1.5)
    assert ba is None


def test_sequence_gap_triggers_resnapshot() -> None:
    book = L2Book(symbol="BTCUSDT")
    events = [
        {
            "type": "snapshot",
            "seq": 10,
            "ts": 1000,
            "bids": [[100.0, 1.0]],
            "asks": [[100.2, 2.0]],
        },
        {"type": "delta", "seq": 11, "ts": 1001, "bids": [[100.1, 1.0]], "asks": []},
        # gap: jump to 13, should flag resnapshot
        {"type": "delta", "seq": 13, "ts": 1002, "bids": [[100.0, 0.0]], "asks": []},
        {
            "type": "snapshot",
            "seq": 20,
            "ts": 1010,
            "bids": [[101.0, 3.0]],
            "asks": [[101.2, 1.0]],
        },
    ]
    book, resnap = process_stream(book, events)
    assert resnap == 1
    assert book.seq == 20
    assert book.best_bid() == (101.0, 3.0)
    assert book.best_ask() == (101.2, 1.0)
