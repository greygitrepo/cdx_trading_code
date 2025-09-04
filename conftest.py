"""Configure test environment and enforce stub-only, no-network tests."""

from __future__ import annotations

import sys
from pathlib import Path
import socket
import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _stub_env_and_block_network(monkeypatch):
    # Force stub/paper modes and disable live/testnet in tests/CI
    monkeypatch.setenv("STUB_MODE", "true")
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("LIVE_MODE", "false")
    monkeypatch.setenv("TESTNET", "false")
    monkeypatch.setenv("MPLBACKEND", "Agg")

    # Block network access: prevent creating outbound socket connections
    def _no_network(*args, **kwargs):  # noqa: ANN001, D401
        raise RuntimeError("Network access blocked in tests/CI")

    monkeypatch.setattr(socket, "create_connection", _no_network)
