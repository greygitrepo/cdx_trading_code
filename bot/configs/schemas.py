"""Pydantic-based configuration schemas and YAML loader.

These schemas define runtime configuration and parameter packs for the trading system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

try:  # Prefer pydantic v2
    from pydantic import BaseModel, Field
except (
    Exception
):  # pragma: no cover - lightweight fallback if pydantic absent at runtime
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
    prefer_maker_bps_threshold: float = Field(
        0.04, description="Spread threshold in % for maker preference"
    )
    maker_post_only: bool = True
    taker_on_strong_score: bool = True
    fallback_ioc: bool = True


class RiskConfig(BaseModel):
    """Risk limits and sizing."""

    max_leverage: int = 10
    max_alloc_pct: float = 0.02
    risk_per_trade_min: float = 0.003
    risk_per_trade_max: float = 0.006
    daily_max_loss: float = 0.02
    per_symbol_concentration: float = 0.40
    # Multi-symbol management
    max_symbols: int = 5
    total_budget_usdt: float | None = None
    use_balance_ratio: float = 1.0
    min_free_balance_usdt: float = 100.0


class RegimeParams(BaseModel):
    crash_z: float = 4.0
    spread_mult_pause: float = 3.0
    pause_minutes: int = 3
    resume_rv_z: float = 1.5
    resume_spread_mult: float = 1.3
    resume_depth_recover: float = 0.80
    oi_drop_pct: float = 2.0
    strictness: Literal["off", "loose", "strict"] = "strict"


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
    # Number of L2 levels to consider when computing imbalance and building OB snapshot
    depth_levels: int = 1


class OBFlowParams(BaseModel):
    """Thresholds for OB-Flow pattern signals (A/B/C/D).

    Keep defaults conservative; profiles may override in YAML.
    """

    depth_imb_L5_min: float = 0.3
    spread_tight_mult_mid: float = 0.0006
    tps_min_breakout: float = 8.0
    c_absorption_min: float = 0.5
    d_wide_spread_mult_mid: float = 0.0025
    d_micro_dev_mult_spread: float = 0.65


class ExecutionRoutingParams(BaseModel):
    """Dynamic routing thresholds and toggles.

    If dynamic_taker_on_strong is true, maker→taker 승격 조건을 아래 임계값 2개 이상 충족 시 적용.
    """

    dynamic_taker_on_strong: bool = True
    tps_min: float = 8.0
    imb_l5_min: float = 0.25
    spread_max: float = 0.0006
    breakout_sigma: float = 0.0


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
    # Global spread threshold (pct of mid) used in regime pause check
    spread_threshold_pct: float = 0.0004


class ParamsPack(BaseModel):
    """Aggregate parameters for strategies and regime."""

    universe: UniverseParams = UniverseParams()
    regime: RegimeParams = RegimeParams()
    indicators: IndicatorParams = IndicatorParams()
    orderbook: OrderBookParams = OrderBookParams()
    obflow: OBFlowParams = OBFlowParams()
    execution: ExecutionRoutingParams = ExecutionRoutingParams()
    entry_exit: EntryExitParams = EntryExitParams()
    funding_time: FundingTimeParams = FundingTimeParams()


class StrategySelection(BaseModel):
    """Strategy selection and parameters for plugin architecture."""

    name: str = Field("obflow")  # default OB-Flow
    params: dict = Field(default_factory=dict)


class AppConfig(BaseModel):
    """Top-level application config."""

    data_path: Path = Field(Path("data/stubs"))
    example_param: int = 1
    exchange: ExchangeConfig = ExchangeConfig()
    risk: RiskConfig = RiskConfig()
    params: ParamsPack = ParamsPack()
    # New strategy section (behavior-preserving default is obflow)
    strategy: StrategySelection = Field(default_factory=StrategySelection)
    runtime: "RuntimeOptions" = Field(default_factory=lambda: RuntimeOptions())


class RuntimeOptions(BaseModel):
    """Runtime toggles that are not strategy params.

    Exposed in `config.yaml` under `runtime`. Currently supports strategy selection.
    """

    strategy: Literal["pack", "obflow", "apex"] = Field(
        "pack",
        description="Deprecated: prefer AppConfig.strategy.name. Kept for back-compat.",
    )
    # Discovery/rotation
    discover_symbols: bool = True
    consensus_ticks: int = 3
    no_trade_sleep_sec: float = 5.0
    loop_idle_sec: float = 1.0
    exit_key: str = "q"
    refresh_universe_each_loop: bool = True
    # Behavior toggles
    avoid_duplicate_symbol: bool = True
    allow_flip: bool = False
    invert_signals: bool = False
    attach_tpsl_on_create: bool = False
    summary_interval_sec: int = 600


try:
    AppConfig.model_rebuild()  # type: ignore[attr-defined]
except Exception:
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def load_app_config(path: Path) -> AppConfig:
    obj = load_yaml(path)
    # Backward compatible: allow missing `runtime`/`strategy` sections
    if "strategy" not in obj:
        obj["strategy"] = {"name": obj.get("runtime", {}).get("strategy", "obflow"), "params": {}}
    app = AppConfig(**obj)
    runtime_obj = obj.get("runtime") if isinstance(obj, dict) else None
    try:
        rt = RuntimeOptions(**(runtime_obj or {}))
    except Exception:
        rt = RuntimeOptions()
    setattr(app, "runtime", rt)
    return app


def load_params(path: Path) -> ParamsPack:
    obj = load_yaml(path)
    return ParamsPack(**obj)
