"""Stub script to export reports."""

from __future__ import annotations
from pathlib import Path


def main() -> None:
    """Export generated reports."""
    reports = Path("reports")
    if not reports.exists():
        print("No reports found.")
        return
    for path in reports.glob("*.html"):
        print(f"Exporting {path}")


if __name__ == "__main__":
    main()
