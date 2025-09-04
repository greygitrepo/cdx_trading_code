"""Generate a dummy paper trading report (headless-safe)."""

from __future__ import annotations
from pathlib import Path
import os
import sys

# ruff: noqa: E402  (ensure running as script works without PYTHONPATH)
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")  # headless CI
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
