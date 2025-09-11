"""Dummy mean-reversion strategy example used for tests/docs."""

from __future__ import annotations

from typing import Any, Optional

try:
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        pass

from bot.core.strategy_api import BaseStrategy, OrderIntent, ExitIntent
from bot.core.types import Side


class DummyMRConfig(BaseModel):
    window: int = 5
    threshold: float = 0.001


class DummyMeanReversion(BaseStrategy):
    name = "dummy_mean_reversion"
    ConfigModel = DummyMRConfig

    def __init__(self, cfg: DummyMRConfig, app_ctx: Any | None = None) -> None:
        super().__init__(cfg, app_ctx)
        self._closes: list[float] = []

    def score_tick(self, ob_event: Any) -> float:
        price = float(getattr(ob_event, "last", getattr(ob_event, "price", 0.0)))
        if not price:
            return 0.0
        self._closes.append(price)
        if len(self._closes) < self.cfg.window:
            return 0.0
        avg = sum(self._closes[-self.cfg.window :]) / self.cfg.window
        dev = (price - avg) / avg if avg else 0.0
        return float(abs(dev))

    def should_enter(self, state: Any) -> Optional[OrderIntent]:
        if len(self._closes) < self.cfg.window:
            return None
        avg = sum(self._closes[-self.cfg.window :]) / self.cfg.window
        price = self._closes[-1]
        dev = (price - avg) / avg if avg else 0.0
        if dev <= -self.cfg.threshold:
            return OrderIntent(side=Side.BUY, qty=1.0)
        if dev >= self.cfg.threshold:
            return OrderIntent(side=Side.SELL, qty=1.0)
        return None

    def should_exit(self, state: Any) -> Optional[ExitIntent]:  # pragma: no cover
        return None

    def update(self, event: Any) -> None:  # pragma: no cover
        return None
