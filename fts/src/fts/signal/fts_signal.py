from __future__ import annotations

from pydantic import BaseModel

from ..common.types import Event, Signal


class FTSConfig(BaseModel):
    penetration_ticks: int = 4
    z_flow_min: float = 3.0
    depth_ratio_max: float = 0.45
    lambda_drop_max: float = 0.45
    tp_bps: list[int] = [25, 15]
    sl_bps: int = 18


def evaluate_fts(event: Event, cfg: FTSConfig) -> Signal | None:
    cond1 = abs(event.price - event.anchor) >= cfg.penetration_ticks
    cond2 = event.z_flow >= cfg.z_flow_min
    cond3 = event.depth_ratio <= cfg.depth_ratio_max
    cond4 = (
        event.lambda_drop <= cfg.lambda_drop_max
        and ((event.price > event.anchor and event.microprice < event.anchor) or (
            event.price < event.anchor and event.microprice > event.anchor
        ))
    )
    if cond1 and cond2 and cond3 and cond4:
        side = "SELL" if event.price > event.anchor else "BUY"
        return Signal(side=side, tp_bps=cfg.tp_bps[0], sl_bps=cfg.sl_bps)
    return None
