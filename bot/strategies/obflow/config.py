from __future__ import annotations

"""Pydantic config model for OB-Flow strategy."""

try:
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        pass


class OBFlowConfig(BaseModel):
    depth_imb_L5_min: float = 0.18
    spread_tight_mult_mid: float = 0.0008
    tps_min_breakout: float = 8.0
    c_absorption_min: float = 0.35
    d_wide_spread_mult_mid: float = 0.0015
    d_micro_dev_mult_spread: float = 0.40

