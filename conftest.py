"""Configure test environment and enforce stub-only, no-network tests."""

from __future__ import annotations

import sys
from pathlib import Path
import socket
import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _has_testnet_creds() -> bool:
    import os

    return (
        os.getenv("TESTNET", "false").lower() == "true"
        and os.getenv("LIVE_MODE", "false").lower() == "true"
        and os.getenv("STUB_MODE", "true").lower() == "false"
        and os.getenv("PAPER_MODE", "true").lower() == "false"
        and os.getenv("BYBIT_API_KEY")
        and os.getenv("BYBIT_API_SECRET")
    )


@pytest.fixture(autouse=True)
def _env_and_optional_block_network(monkeypatch):
    # Default to stub/paper unless integration env explicitly provided
    if not _has_testnet_creds():
        monkeypatch.setenv("STUB_MODE", "true")
        monkeypatch.setenv("PAPER_MODE", "true")
        monkeypatch.setenv("LIVE_MODE", "false")
        monkeypatch.setenv("TESTNET", "false")

        # Block network in unit/default runs
        def _no_network(*args, **kwargs):  # noqa: ANN001, D401
            raise RuntimeError("Network access blocked in tests/CI")

        monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setenv("MPLBACKEND", "Agg")
