"""Stub reporting module."""

from __future__ import annotations
from pathlib import Path


def generate_report(path: Path) -> None:
    """Create an empty report file."""
    path.write_text("<html></html>")

