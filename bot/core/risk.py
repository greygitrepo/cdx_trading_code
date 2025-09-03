"""Risk management utilities: sizing and stops."""

from __future__ import annotations

from dataclasses import dataclass


def position_size(balance: float, risk_fraction: float) -> float:
    return max(0.0, balance * max(0.0, risk_fraction))


@dataclass
class Stops:
    stop_loss: float
    take_profit: float
    trailing: float


def compute_stops(entry: float, tp: float, sl: float, trail: float, side_long: bool) -> Stops:
    if side_long:
        return Stops(stop_loss=entry * (1 - sl), take_profit=entry * (1 + tp), trailing=trail)
    return Stops(stop_loss=entry * (1 + sl), take_profit=entry * (1 - tp), trailing=trail)


def daily_loss_gate(equity_start: float, equity_now: float, daily_max_loss: float) -> bool:
    return (equity_start - equity_now) / max(1e-12, equity_start) >= daily_max_loss

