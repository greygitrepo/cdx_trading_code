"""Paper report runner."""

from __future__ import annotations
from pathlib import Path

from bot.core.reporting import generate_report


class PaperRunner:
    def __init__(self, out_dir: str = "reports", filename: str = "paper.html") -> None:
        self.out_dir = Path(out_dir)
        self.filename = filename

    def run(self) -> Path:
        self.out_dir.mkdir(exist_ok=True)
        report_file = self.out_dir / self.filename
        generate_report(report_file)
        return report_file
