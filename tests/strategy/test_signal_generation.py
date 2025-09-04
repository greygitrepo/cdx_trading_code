from __future__ import annotations

import json
from pathlib import Path
import pytest


pytestmark = [pytest.mark.strategy, pytest.mark.unit]


def test_signal_expected_on_known_window():
    from bot.core.strategies import (
        StrategyParams,
        mis_signal,
        vrs_signal,
        select_strategy,
    )

    path = Path("tests/fixtures/candles_btc_1m_small.json")
    data = json.loads(path.read_text())
    closes = [row["c"] for row in data]
    vols = [row["v"] for row in data]

    params = StrategyParams(ema_fast=3, ema_slow=9, rsi2_low=4, vwap_dev_for_vrs=0.0035)
    # Construct favorable OBI/spread
    side_mis, score_mis = mis_signal(
        closes,
        orderbook_imbalance=0.70,
        spread=0.0003,
        spread_threshold=0.0005,
        params=params,
    )
    side_vrs, score_vrs = vrs_signal(closes, vols, params)
    name, side = select_strategy(
        (side_mis, score_mis), (side_vrs, score_vrs), (None, 0.0)
    )
    assert name in {"MIS", "VRS"}
    assert side is not None
