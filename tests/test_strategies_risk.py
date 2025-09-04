"""Tests for strategies signals and risk utilities."""

from __future__ import annotations

from bot.core.strategies import (
    StrategyParams,
    mis_signal,
    vrs_signal,
    lsr_signal,
    select_strategy,
)
from bot.core.risk import position_size, compute_stops, daily_loss_gate
from bot.core.types import Side


def test_mis_long_signal_and_select() -> None:
    closes = [100, 100.1, 100.2, 100.3, 100.4]
    side, score = mis_signal(
        closes,
        orderbook_imbalance=0.65,
        spread=0.0003,
        spread_threshold=0.0004,
        params=StrategyParams(),
    )
    assert side == Side.BUY and score > 0.0
    name, chosen = select_strategy((side, score), (None, 0.0), (None, 0.0))
    assert name == "MIS" and chosen == Side.BUY


def test_vrs_short_signal() -> None:
    closes = [100, 100.5, 100.7, 100.9]
    vols = [10, 10, 10, 10]
    side, score = vrs_signal(closes, vols, StrategyParams(vwap_dev_for_vrs=0.003))
    # could be BUY or SELL depending on deviation sign; craft down dev
    closes = [100, 99.0, 98.9, 98.8]
    side, score = vrs_signal(closes, vols, StrategyParams(vwap_dev_for_vrs=0.003))
    assert side == Side.SELL and score > 0


def test_lsr_conditions() -> None:
    side, score = lsr_signal(wick_long=True, trade_burst=True, oi_drop=True)
    assert side == Side.SELL and score == 1.0


def test_risk_and_stops() -> None:
    size = position_size(balance=100.0, risk_fraction=0.005)
    assert size == 0.5
    stops = compute_stops(entry=100.0, tp=0.001, sl=0.002, trail=0.0008, side_long=True)
    assert stops.stop_loss == 99.8 and stops.take_profit == 100.1
    assert (
        daily_loss_gate(equity_start=100.0, equity_now=97.9, daily_max_loss=0.02)
        is True
    )
