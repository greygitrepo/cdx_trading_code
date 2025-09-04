from __future__ import annotations

import pytest


pytestmark = [pytest.mark.strategy, pytest.mark.unit]


def test_simple_position_fsm_with_signals():
    # Using FakeExchangeClient to simulate position creation and reduce-only exit
    from tests.helpers.fakes import FakeExchangeClient, MarketRule

    ex = FakeExchangeClient(
        {"BTCUSDT": MarketRule(0.001, 0.1, 5.0)}, {"BTCUSDT": 100.0}
    )
    sym = "BTCUSDT"
    # ENTRY
    ex.place_order(sym, "buy", 1.0)
    assert ex.get_position_size(sym) == 1.0
    # SCALE-UP
    ex.place_order(sym, "buy", 0.5)
    assert ex.get_position_size(sym) == 1.5
    # REDUCE via reduce-only
    ex.place_order(sym, "sell", 0.4, reduce_only=True)
    assert abs(ex.get_position_size(sym) - 1.1) < 1e-9
    # EXIT
    ex.close_position(sym)
    assert ex.get_position_size(sym) == 0.0
