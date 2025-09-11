"""Live runner internal entrypoint used by scripts.

This runner focuses on strategy selection metadata (name + config hash)
so scripts can preserve their existing behavior while recording strategy
provenance for reproducibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from bot.app.wiring import AppContext, build_strategy_from_config


@dataclass
class StrategyHeader:
    """Metadata for logging at run start to help reproducibility."""

    strategy_name: str
    strategy_cfg_hash: str
    params: Dict[str, Any]


class LiveRunner:
    """Lightweight facade for live-testnet script.

    Existing script logic remains unchanged; we only standardize strategy
    selection and provide a header to log into events.jsonl.
    """

    @staticmethod
    def compute_cfg_hash(params: Dict[str, Any]) -> str:
        raw = json.dumps(params or {}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def build_header(*, app_ctx: Optional[AppContext], config: Any) -> StrategyHeader:
        # Instantiate to ensure registry path is valid
        _ = build_strategy_from_config(config, app_ctx)
        name = getattr(config.strategy, "name", getattr(config.runtime, "strategy", "obflow"))
        params = getattr(config.strategy, "params", {}) or {}
        return StrategyHeader(
            strategy_name=str(name),
            strategy_cfg_hash=LiveRunner.compute_cfg_hash(params),
            params=params,
        )

    @staticmethod
    def run(*_, **__):  # pragma: no cover - placeholder for future expansion
        """Reserved hook if we migrate full loop here later."""
        return None
