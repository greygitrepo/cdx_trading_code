"""Generate a dummy paper trading report."""

from __future__ import annotations
from pathlib import Path

from bot.core.reporting import generate_report


def main() -> None:
    """Create a simple HTML report for paper trading."""
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    report_file = reports / "paper.html"
    generate_report(report_file)
    print(f"Report generated at {report_file}")


if __name__ == "__main__":
    main()
