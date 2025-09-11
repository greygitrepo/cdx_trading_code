"""OB-Flow v2: Testnet live loop (thin wrapper).

This script now delegates to LiveTestnetRunner with strategy fixed to 'obflow'.
It preserves environment-driven behavior but centralizes logic in the app runner.
"""

from __future__ import annotations

import argparse
import sys
from types import SimpleNamespace as _NS
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    from bot.app.runners.live_testnet_runner import LiveTestnetRunner  # lazy import

    ap = argparse.ArgumentParser(description="Run OB-Flow live testnet (delegated)")
    ap.add_argument("--profile", default="", help="profile name (e.g., quick-test)")
    args = ap.parse_args()
    # Build namespace compatible with run_main signature
    ns = _NS(strategy="obflow", strategy_param=[], profile=(args.profile or None))
    LiveTestnetRunner.run_main(ns)


if __name__ == "__main__":
    main()
