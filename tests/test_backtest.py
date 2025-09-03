"""Tests for backtest module."""

from bot.core.backtest import run_backtest


def test_run_backtest() -> None:
    """Backtest should return zero trades in stub."""
    result = run_backtest()
    assert result["trades"] == 0
