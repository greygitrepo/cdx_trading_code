"""OB-Flow strategy wrapper adhering to BaseStrategy API.

Delegates signal decision to existing `bot.core.signals.obflow.decide` to
preserve behavior.
"""

from __future__ import annotations

from typing import Any, Optional

from bot.core.strategy_api import BaseStrategy, ExitIntent, OrderIntent
from bot.core.types import Side
from bot.strategies.obflow.config import OBFlowConfig
from bot.core.signals.obflow import decide as obflow_decide, OBFlowConfig as _OldCfg


class OBFlowStrategy(BaseStrategy):
    name = "obflow"
    ConfigModel = OBFlowConfig

    def __init__(self, cfg: OBFlowConfig, app_ctx: Any | None = None) -> None:  # type: ignore[override]
        super().__init__(cfg, app_ctx)
        # Bridge to existing dataclass-based config used by decide()
        self._decider_cfg = _OldCfg(
            depth_imb_L5_min=float(cfg.depth_imb_L5_min),
            spread_tight_mult_mid=float(cfg.spread_tight_mult_mid),
            tps_min_breakout=float(cfg.tps_min_breakout),
            c_absorption_min=float(cfg.c_absorption_min),
            d_wide_spread_mult_mid=float(cfg.d_wide_spread_mult_mid),
            d_micro_dev_mult_spread=float(cfg.d_micro_dev_mult_spread),
        )
        self._last_score: float = 0.0

    def score_tick(self, ob_event: Any) -> float:
        sig = obflow_decide(ob_event, self._decider_cfg)
        if sig is None:
            self._last_score = 0.0
            return 0.0
        self._last_score = float(sig.get("score", 0.0))
        return self._last_score

    def should_enter(self, state: Any) -> Optional[OrderIntent]:  # pragma: no cover - adapter
        # Stateless adapter: if last score is positive and side exists, propose an entry
        sig = getattr(state, "_obflow_signal", None)
        if sig is None:
            return None
        side = Side.BUY if str(sig.get("side")) == "BUY" else Side.SELL
        return OrderIntent(side=side, qty=float(getattr(state, "proposed_qty", 0.0)) or 0.0)

    def should_exit(self, state: Any) -> Optional[ExitIntent]:  # pragma: no cover - adapter
        return None

    def update(self, event: Any) -> None:
        # No internal state tracking in this thin wrapper
        return None
