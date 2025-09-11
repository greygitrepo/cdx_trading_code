"""Strategy registry and loader.

Allows registration via string entrypoints or callables.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, Union

from bot.core.strategy_api import BaseStrategy, StrategyConfigError


STRATEGY_REGISTRY: Dict[str, Union[str, Callable[..., BaseStrategy]]] = {
    # Default strategy maps to OB-Flow implementation
    "obflow": "bot.strategies.obflow.strategy:OBFlowStrategy",
}


def register(name: str, target: Union[str, Callable[..., BaseStrategy]]) -> None:
    if name in STRATEGY_REGISTRY:
        raise StrategyConfigError(f"Strategy '{name}' already registered")
    STRATEGY_REGISTRY[name] = target


def _load_from_string(path: str) -> Callable[..., BaseStrategy]:
    if ":" not in path:
        raise StrategyConfigError(
            f"Invalid strategy entrypoint '{path}'. Use 'module.sub:ClassName'"
        )
    mod, obj = path.split(":", 1)
    try:
        m = importlib.import_module(mod)
        factory = getattr(m, obj)
    except Exception as e:  # pragma: no cover - defensive
        raise StrategyConfigError(f"Failed to import strategy '{path}': {e}") from e
    if not callable(factory):
        raise StrategyConfigError(f"Entrypoint '{path}' is not callable")
    return factory


def load_strategy(name: str, params: Dict[str, Any], app_ctx: Any | None) -> BaseStrategy:
    if name not in STRATEGY_REGISTRY:
        raise StrategyConfigError(f"Strategy '{name}' is not registered")
    target = STRATEGY_REGISTRY[name]
    factory = _load_from_string(target) if isinstance(target, str) else target
    # Validate/configure via ConfigModel
    # Construct a temporary instance to access ConfigModel, or access attribute on factory
    ConfigModel = getattr(factory, "ConfigModel", None)
    if ConfigModel is None:
        # class method attr not present until class is resolved; instantiate class then check
        ConfigModel = getattr(getattr(factory, "__self__", factory), "ConfigModel", None)
    try:
        cfg = ConfigModel(**(params or {})) if ConfigModel is not None else params or {}
    except Exception as e:
        raise StrategyConfigError(f"Invalid params for '{name}': {e}") from e
    return factory(cfg, app_ctx)
