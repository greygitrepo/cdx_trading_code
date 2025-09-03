"""Pydantic-based configuration schemas and YAML loader.

These schemas define runtime configuration and parameter packs for the trading system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

try:  # Prefer pydantic v2
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - lightweight fallback if pydantic absent at runtime
    # Minimal shim to avoid hard dependency during non-config tests
    from dataclasses import dataclass as BaseModel  # type: ignore[assignment]

    def Field(default: Any = None, **_: Any) -> Any:  # type: ignore[override]
        return default

import yaml


class ExchangeConfig(BaseModel):
    """Exchange connectivity and trade defaults."""

    name: Literal["bybit"] = Field("bybit")
    network: Literal["testnet", "mainnet"] = Field("testnet")
    category: Literal["linear", "inverse", "spot"] = Field("linear")
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT"])
    prefer_maker_bps_threshold: float = Field(0.04, description="Spread threshold in % for maker preference")
    maker_post_only: bool = True
    taker_on_strong_score: bool = True
    fallback_ioc: bool = True


class RiskConfig(BaseModel):
    """Risk limits and sizing."""

    max_leverage: int = 10
    risk_per_trade_min: float = 0.003
    risk_per_trade_max: float = 0.006
    daily_max_loss: float = 0.02
    per_symbol_concentration: float = 0.40


class RegimeParams(BaseModel):
    crash_z: float = 4.0
    spread_mult_pause: float = 3.0
    pause_minutes: int = 3
    resume_rv_z: float = 1.5
    resume_spread_mult: float = 1.3
    resume_depth_recover: float = 0.80
    oi_drop_pct: float = 2.0


class IndicatorParams(BaseModel):
    ema_fast: int = 3
    ema_slow: int = 9
    adx_len: int = 7
    keltner_len: int = 20
    keltner_mult: float = 1.25
    rsi2_low: int = 4
    rsi2_high: int = 96


class OrderBookParams(BaseModel):
    obi_window_ms: int = 1500
    obi_threshold_mis: float = 0.60
    min_depth_usd: int = 15000


class EntryExitParams(BaseModel):
    tp1: float = 0.0010
    trail_after_tp1: float = 0.0008
    time_stop_mis: str = "30-40"
    time_stop_vrs: str = "20-30"
    time_stop_lsr: str = "15-25"


class FundingTimeParams(BaseModel):
    avoid_taker_within_min: int = 5


class UniverseParams(BaseModel):
    topN: int = 12
    spread_max_mult: float = 1.5
    depth_drop_pause: float = 0.70
    vwap_dev_for_vrs: float = 0.0035


class ParamsPack(BaseModel):
    """Aggregate parameters for strategies and regime."""

    universe: UniverseParams = UniverseParams()
    regime: RegimeParams = RegimeParams()
    indicators: IndicatorParams = IndicatorParams()
    orderbook: OrderBookParams = OrderBookParams()
    entry_exit: EntryExitParams = EntryExitParams()
    funding_time: FundingTimeParams = FundingTimeParams()


class AppConfig(BaseModel):
    """Top-level application config."""

    data_path: Path = Field(Path("data/stubs"))
    example_param: int = 1
    exchange: ExchangeConfig = ExchangeConfig()
    risk: RiskConfig = RiskConfig()
    params: ParamsPack = ParamsPack()


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def load_app_config(path: Path) -> AppConfig:
    obj = load_yaml(path)
    return AppConfig(**obj)


def load_params(path: Path) -> ParamsPack:
    obj = load_yaml(path)
    return ParamsPack(**obj)
