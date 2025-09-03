"""Stub data feed module."""

from __future__ import annotations


class DataFeed:
    """Provide stubbed market data."""

    def stream(self) -> list[str]:
        """Return sample market data."""
        return ["tick1", "tick2"]
