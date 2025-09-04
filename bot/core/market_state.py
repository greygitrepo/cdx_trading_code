"""Market regime detector (Pause/Resume) based on simple thresholds.

Implements pause when 2+ conditions are met, resume when conditions ease.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RegimeParams:
    crash_z: float = 4.0
    spread_mult_pause: float = 3.0
    pause_minutes: int = 3
    resume_rv_z: float = 1.5
    resume_spread_mult: float = 1.3
    resume_depth_recover: float = 0.80
    oi_drop_pct: float = 2.0


@dataclass
class RegimeDetector:
    p: RegimeParams
    paused: bool = False

    def check_pause(
        self,
        z_1s: float,
        spread_mult: float,
        depth_drop: float,
        oi_drop_pct: float,
        ws_drop_rate: float,
    ) -> bool:
        triggers = 0
        triggers += 1 if z_1s >= self.p.crash_z else 0
        triggers += 1 if spread_mult >= self.p.spread_mult_pause else 0
        triggers += 1 if depth_drop >= self.p.resume_depth_recover else 0
        triggers += (
            1 if (oi_drop_pct >= self.p.oi_drop_pct and ws_drop_rate > 0.0) else 0
        )
        self.paused = triggers >= 2 or self.paused
        return self.paused

    def check_resume(
        self, rv_z: float, spread_mult: float, depth_recover: float
    ) -> bool:
        if (
            self.paused
            and rv_z <= self.p.resume_rv_z
            and spread_mult <= self.p.resume_spread_mult
            and depth_recover >= self.p.resume_depth_recover
        ):
            self.paused = False
        return not self.paused
