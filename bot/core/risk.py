"""Stub risk module."""

from __future__ import annotations


def position_size(balance: float, risk_fraction: float) -> float:
    """Calculate position size."""
    return balance * risk_fraction
