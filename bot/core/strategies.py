"""Stub strategies module."""

from __future__ import annotations


def select_strategy(score_a: int, score_b: int) -> str:
    """Select strategy with higher score."""
    return "A" if score_a >= score_b else "B"
