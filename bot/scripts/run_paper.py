"""Generate a dummy paper trading report (headless-safe)."""

from __future__ import annotations
import os
import sys

# ruff: noqa: E402  (ensure running as script works without PYTHONPATH)
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")  # headless CI
from bot.app.runners.paper_runner import PaperRunner


def main() -> None:
    """Create a simple HTML report for paper trading."""
    report_file = PaperRunner().run()
    print(f"Report generated at {report_file}")


if __name__ == "__main__":
    main()
