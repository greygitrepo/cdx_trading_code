"""Stub persistence module."""

from __future__ import annotations
from pathlib import Path


def save_log(path: Path, message: str) -> None:
    """Save a log message."""
    path.write_text(message)
