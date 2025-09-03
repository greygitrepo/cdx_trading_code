"""Test that report is generated with expected sections."""

from __future__ import annotations

from pathlib import Path

from bot.core.reporting import generate_report


def test_generate_report_creates_html(tmp_path: Path) -> None:
    path = tmp_path / "paper.html"
    generate_report(path, {"trades": 1, "pnl": 0.1234, "max_dd": 0.01, "slip_bps": 0.5, "win_rate": 0.55})
    content = path.read_text()
    assert "Paper Report" in content
    assert "Trades: 1" in content
