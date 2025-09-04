from __future__ import annotations

import pytest
from tests.helpers.fakes import FakeExchangeClient, MarketRule


@pytest.mark.unit
def test_candle_and_markprice_parsing_unit():
    client = FakeExchangeClient(
        rules={"BTCUSDT": MarketRule(0.001, 0.1, 5.0)},
        prices={"BTCUSDT": 60000.0},
    )
    px = client.get_mark_price("BTCUSDT")
    assert px > 0
    rule = client.get_market_rules("BTCUSDT")
    assert rule.lot_step > 0 and rule.tick_size > 0


@pytest.mark.integration
@pytest.mark.timeout(60)
def test_fetch_testnet_candles_and_rules_integration():
    import os
    from bot.core.exchange.bybit_v5 import EdgeProtectionError
    from bot.exchange.bybit_testnet import BybitClientTestnet

    ex = BybitClientTestnet()
    try:
        # lightweight healthcheck via tickers to avoid heavy endpoints
        px = ex.get_mark_price("BTCUSDT", category="linear")
        # Retrieve market rules (instruments-info); may be protected in CI
        rule = ex.get_market_rules("BTCUSDT")
    except EdgeProtectionError as e:
        if os.getenv("GITHUB_ACTIONS") == "true":
            pytest.skip(f"Bybit public edge protection in CI: {e}")
        raise
    assert rule and px > 0
