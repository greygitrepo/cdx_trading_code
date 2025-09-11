"""Run OB-Flow quicktest loop on TESTNET with aggressive params."""
from __future__ import annotations
import os

from bot.app.runners.quicktest_runner import QuickTestRunner


def main() -> None:
    # Safety/env
    os.environ.setdefault("TESTNET", "true")
    os.environ.setdefault("LIVE_MODE", "true")
    os.environ.setdefault("STUB_MODE", "false")
    sym = os.environ.get("BYBIT_SYMBOL", "BTCUSDT")
    QuickTestRunner().run(symbol=sym, ticks=100)


if __name__ == "__main__":
    main()
