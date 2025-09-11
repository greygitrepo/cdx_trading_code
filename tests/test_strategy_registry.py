from __future__ import annotations

import pytest

from bot.strategies.registry import STRATEGY_REGISTRY, load_strategy, register
from bot.core.strategy_api import StrategyConfigError


def test_obflow_registered_and_loads():
    assert "obflow" in STRATEGY_REGISTRY
    s = load_strategy("obflow", {}, None)
    assert s.name == "obflow"


def test_register_duplicate_raises():
    with pytest.raises(StrategyConfigError):
        register("obflow", "bot.strategies.obflow.strategy:OBFlowStrategy")


def test_missing_raises():
    with pytest.raises(StrategyConfigError):
        load_strategy("missing_strat", {}, None)

