from __future__ import annotations

import pytest


pytestmark = [pytest.mark.ops, pytest.mark.integration]


def test_ops_smoke_loop_max3ticks():
    from bot.core.orchestrator import Orchestrator
    from bot.exchange.bybit_testnet import BybitClientTestnet
    from bot.core.slot_manager import SlotManager
    from bot.selector.symbol_selector import top_n

    ex = BybitClientTestnet()
    sm = SlotManager(max_slots=5)
    orch = Orchestrator(ex=ex, slot_mgr=sm, leverage=5.0, max_symbols=5, total_budget_usdt=1000.0)

    exclude = set(ex.position_symbols()) | set(ex.open_order_symbols())
    # Provide a simple candidate list; orchestrator uses top_n internally
    cands = top_n(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"], 5, exclude_symbols=exclude)

    # Run up to 3 ticks; assert no exceptions and loop completes
    orch.run_loop(max_ticks=3, bootstrap_candidates=cands)

