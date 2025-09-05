from __future__ import annotations

import pytest
from tests.helpers.fakes import FakeExchangeClient, MarketRule, round_by_step


@pytest.mark.unit
def test_long_short_entry_exit_unit():
    rules = {"BTCUSDT": MarketRule(0.001, 0.1, 5.0)}
    prices = {"BTCUSDT": 60000.0}
    ex = FakeExchangeClient(rules, prices)

    budget = 200.0
    px = ex.get_mark_price("BTCUSDT")
    qty = budget / px  # leverage 1x for unit test
    qty = round_by_step(qty, rules["BTCUSDT"].lot_step)
    assert qty > 0

    # LONG ENTRY
    ex.place_order("BTCUSDT", "buy", qty)
    assert ex.positions["BTCUSDT"] > 0

    # LONG EXIT
    ex.place_order("BTCUSDT", "sell", qty, reduce_only=True)
    assert abs(ex.positions.get("BTCUSDT", 0.0)) < 1e-8

    # SHORT ENTRY
    ex.place_order("BTCUSDT", "sell", qty)
    assert ex.positions["BTCUSDT"] < 0

    # SHORT EXIT
    ex.place_order("BTCUSDT", "buy", qty, reduce_only=True)
    assert abs(ex.positions.get("BTCUSDT", 0.0)) < 1e-8


@pytest.mark.integration
def test_long_short_chain_on_testnet_integration():
    from bot.exchange.bybit_testnet import BybitClientTestnet

    ex = BybitClientTestnet()
    sym = "BTCUSDT"
    rule = ex.get_market_rules(sym)
    px = ex.get_mark_price(sym)
    # Minimal qty by step scaled to ~10 USDT notionals
    qty = max(getattr(rule, "lot_step", 0.001) or 0.001, (10.0 / max(px, 1e-6)))
    if getattr(rule, "lot_step", None):
        qty = (int(qty / rule.lot_step)) * rule.lot_step

    from bot.core.exchange.bybit_v5 import BybitAPIError
    try:
        oid = ex.place_order(sym, "buy", qty)
    except BybitAPIError as e:
        # If local creds are invalid/restricted, skip this integration test gracefully
        if getattr(e, "ret_code", 0) in (10003, 10005):
            pytest.skip(f"Testnet API key invalid or restricted: {e}")
        raise
    assert oid is not None
    # Attempt to close position immediately
    ex.close_position(sym)
    assert ex.get_position_size(sym) == 0
