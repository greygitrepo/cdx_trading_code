"""Runtime configuration loader and mode switches.

Modes:
- STUB_MODE: use offline stub data/generators
- PAPER_MODE: simulate fills/backtests
- LIVE_MODE: reserved for real exchange connectivity

Defaults: STUB_MODE=true, PAPER_MODE=true, LIVE_MODE=false
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bot.configs.schemas import AppConfig, load_app_config, load_params, ParamsPack


@dataclass
class Modes:
    stub: bool = True
    paper: bool = True
    live: bool = False


def getenv_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes", "on"}


def get_modes() -> Modes:
    return Modes(
        stub=getenv_bool("STUB_MODE", True),
        paper=getenv_bool("PAPER_MODE", True),
        live=getenv_bool("LIVE_MODE", False),
    )


@dataclass
class RuntimeConfig:
    app: AppConfig
    params: ParamsPack
    modes: Modes


def load_runtime(
    app_path: Path = Path("bot/configs/config.yaml"), params_path: Optional[Path] = None
) -> RuntimeConfig:
    """Load runtime configuration with robust params fallback.

    Priority:
    1) Explicit `params_path` argument
    2) `PARAMS_YAML` env var
    3) If YAML file exists → load; else use `app.params` embedded in app config
    """
    app = load_app_config(app_path)
    # Allow env override
    if params_path is None:
        env_p = os.getenv("PARAMS_YAML")
        if env_p:
            params_path = Path(env_p)
    params: ParamsPack
    if params_path is not None and Path(params_path).exists():
        params = load_params(Path(params_path))
    else:
        # Fallback to embedded params in app config
        params = app.params
    modes = get_modes()
    return RuntimeConfig(app=app, params=params, modes=modes)
