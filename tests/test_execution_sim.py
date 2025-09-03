"""Tests for execution simulation."""

from bot.core.execution import simulate_trade


def test_simulate_trade() -> None:
    """Trade simulation should return 'filled'."""
    assert simulate_trade() == "filled"
