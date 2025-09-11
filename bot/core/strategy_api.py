"""Strategy interface and shared types.

Defines the base class for strategies so new strategies can be plugged in
via the registry without changing application code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Optional, Type

try:
    from pydantic import BaseModel  # type: ignore
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore[override]
        pass

from bot.core.types import Side


class StrategyConfigError(Exception):
    """Raised when a strategy's configuration is invalid."""


class StrategyRuntimeError(Exception):
    """Raised when a strategy encounters a runtime error."""


@dataclass(slots=True)
class OrderIntent:
    """Represents a desired entry order with optional execution hints."""

    side: Side
    qty: float
    post_only: bool | None = None
    time_in_force: str | None = None  # e.g., GTC/IOC/PostOnly
    tp_pct: float | None = None
    sl_pct: float | None = None


@dataclass(slots=True)
class ExitIntent:
    """Represents an intent to exit a position with a reason."""

    reason: str
    qty: float | None = None


class BaseStrategy(ABC):
    """Abstract base class for strategies."""

    name: ClassVar[str] = "base"
    ConfigModel: ClassVar[Type[BaseModel]] = BaseModel

    def __init__(self, cfg: BaseModel, app_ctx: Any | None = None) -> None:
        self.cfg = cfg
        self.app_ctx = app_ctx

    @abstractmethod
    def score_tick(self, ob_event: Any) -> float:
        """Return a score for the current tick/event."""

    @abstractmethod
    def should_enter(self, state: Any) -> Optional[OrderIntent]:
        """Return entry intent if conditions are met, else None."""

    @abstractmethod
    def should_exit(self, state: Any) -> Optional[ExitIntent]:
        """Return exit intent if we should close or reduce position."""

    @abstractmethod
    def update(self, event: Any) -> None:
        """Update internal state with a market or private event."""
