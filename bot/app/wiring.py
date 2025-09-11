"""Dependency wiring and factories.

Assembles strategies from AppConfig using the registry. This module is
kept minimal to avoid changing existing runtime behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

try:
    from pydantic import BaseModel  # type: ignore
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore

from bot.strategies.registry import load_strategy


@dataclass
class AppContext:
    """Minimal app context exposed to strategies.

    Extend as needed. For now it's optional and not used by existing logic.
    """

    router: Any | None = None
    market_data_hub: Any | None = None
    event_bus: Any | None = None


def build_strategy_from_config(config: Any, app_ctx: Optional[AppContext] = None):
    """Build strategy instance using registry and AppConfig.

    Falls back to `config.runtime.strategy` for backward compatibility.
    """
    # Default selection priority: CLI or config.strategy.name > runtime.strategy
    name = getattr(getattr(config, "strategy", object()), "name", None)
    if not name:
        name = getattr(getattr(config, "runtime", object()), "strategy", "obflow")
    params = getattr(getattr(config, "strategy", object()), "params", {}) or {}
    return load_strategy(str(name), params, app_ctx)
