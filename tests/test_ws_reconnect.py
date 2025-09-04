"""Reconnection backoff and recovery tests (offline)."""

from __future__ import annotations

from bot.core.data_feed import exp_backoff


def test_exponential_backoff_caps() -> None:
    gen = exp_backoff(initial=0.1, maximum=0.4)
    vals = [next(gen) for _ in range(5)]
    assert vals == [0.1, 0.2, 0.4, 0.4, 0.4]
