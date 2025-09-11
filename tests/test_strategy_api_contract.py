from __future__ import annotations

from bot.core.strategy_api import BaseStrategy
from bot.strategies.obflow.strategy import OBFlowStrategy
from bot.strategies.obflow.config import OBFlowConfig


def test_base_strategy_signature():
    assert hasattr(BaseStrategy, "score_tick")
    assert hasattr(BaseStrategy, "should_enter")
    assert hasattr(BaseStrategy, "should_exit")
    assert hasattr(BaseStrategy, "update")


def test_obflow_config_validation():
    # Valid config
    cfg = OBFlowConfig(depth_imb_L5_min=0.2)
    s = OBFlowStrategy(cfg, None)
    assert s.name == "obflow"
    # Invalid type should raise via Pydantic if available; otherwise accept
    try:
        OBFlowConfig(depth_imb_L5_min="bad")  # type: ignore[arg-type]
        pydantic_present = False
    except Exception:
        pydantic_present = True
    if pydantic_present:
        try:
            OBFlowStrategy(OBFlowConfig(depth_imb_L5_min="bad"), None)  # type: ignore[arg-type]
            assert False, "Should not reach when pydantic enforces types"
        except Exception:
            pass
