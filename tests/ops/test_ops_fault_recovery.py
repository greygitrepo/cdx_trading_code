from __future__ import annotations

import pytest


pytestmark = [pytest.mark.ops, pytest.mark.integration]


class FlakyWrapper:
    def __init__(self, base, fail_first_n: int = 1):
        self.base = base
        self.fail_first_n = fail_first_n
        self.calls = 0

    # Delegate methods; inject failure on get_mark_price
    def position_symbols(self):
        return self.base.position_symbols()

    def open_order_symbols(self):
        return self.base.open_order_symbols()

    def get_mark_price(self, symbol):
        self.calls += 1
        if self.calls <= self.fail_first_n:
            raise RuntimeError("Injected network fault")
        return self.base.get_mark_price(symbol)

    def get_market_rules(self, symbol):
        return self.base.get_market_rules(symbol)

    def place_order(self, *a, **k):
        return self.base.place_order(*a, **k)

    def close_position(self, *a, **k):
        return self.base.close_position(*a, **k)


def test_fault_recovery_backoff_passes():
    from bot.exchange.bybit_testnet import BybitClientTestnet
    from bot.core.slot_manager import SlotManager
    from bot.core.orchestrator import Orchestrator

    base = BybitClientTestnet()
    ex = FlakyWrapper(base, fail_first_n=2)
    sm = SlotManager(max_slots=2)
    orch = Orchestrator(
        ex=ex, slot_mgr=sm, leverage=5.0, max_symbols=2, total_budget_usdt=200.0
    )
    orch.run_loop(
        max_ticks=1, bootstrap_candidates=["BTCUSDT", "ETHUSDT"], backoff_max=3
    )
