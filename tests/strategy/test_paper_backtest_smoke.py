from __future__ import annotations

from pathlib import Path
import pytest


pytestmark = [pytest.mark.strategy, pytest.mark.unit]


def test_run_paper_generates_report(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from bot.scripts.run_paper import main

    main()
    out = Path("reports/paper.html")
    assert out.exists() and out.stat().st_size > 0
