"""Trade state machine with partial TP, trailing, time stop, and cooldown.

Lightweight helper suitable for live and sim. Stateless functions are preferred
in core; this class encapsulates per-position state for clarity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

Side = Literal["BUY", "SELL"]


@dataclass
class TradeParams:
    tp1: float = 0.0012
    trail_after_tp1: float = 0.0008
    time_stop_sec: int = 900  # default 15m
    partial_pct: float = 0.5


@dataclass
class TradeState:
    side: Side
    entry_price: float
    qty: float
    entry_ts: int  # epoch sec or ms (caller consistent)
    params: TradeParams = field(default_factory=TradeParams)

    # Internal runtime
    realized_qty: float = 0.0
    tp1_done: bool = False
    trailing_active: bool = False
    trail_anchor: Optional[float] = None  # best favorable price seen

    def _is_long(self) -> bool:
        return self.side == "BUY"

    def update(self, px: float, now_ts: int) -> List[dict]:
        """Advance state with latest price; return list of actions.

        Actions: {type: 'partial_close'|'update_trailing'|'time_stop_close', qty?, price?, reason}
        """
        actions: List[dict] = []
        rem = max(0.0, self.qty - self.realized_qty)
        if rem <= 0.0:
            return actions

        # Time stop
        if (now_ts - self.entry_ts) >= self.params.time_stop_sec:
            actions.append({
                "type": "time_stop_close",
                "qty": rem,
                "price": px,
                "reason": "time_stop"
            })
            self.realized_qty = self.qty
            return actions

        # TP1 partial
        if not self.tp1_done:
            target = self.entry_price * (1 + self.params.tp1 if self._is_long() else 1 - self.params.tp1)
            if (px >= target and self._is_long()) or (px <= target and not self._is_long()):
                close_qty = rem * self.params.partial_pct
                if close_qty > 0:
                    actions.append({
                        "type": "partial_close",
                        "qty": close_qty,
                        "price": px,
                        "reason": "tp1"
                    })
                    self.realized_qty += close_qty
                    self.tp1_done = True
                    self.trailing_active = True
                    self.trail_anchor = px

        # Trailing after TP1
        if self.trailing_active:
            # Update anchor to best favorable price
            if self._is_long():
                self.trail_anchor = max(self.trail_anchor or px, px)
                stop = self.trail_anchor * (1 - self.params.trail_after_tp1)
                if px <= stop:
                    actions.append({
                        "type": "partial_close",
                        "qty": rem,
                        "price": px,
                        "reason": "trail_stop"
                    })
                    self.realized_qty = self.qty
            else:
                self.trail_anchor = min(self.trail_anchor or px, px)
                stop = self.trail_anchor * (1 + self.params.trail_after_tp1)
                if px >= stop:
                    actions.append({
                        "type": "partial_close",
                        "qty": rem,
                        "price": px,
                        "reason": "trail_stop"
                    })
                    self.realized_qty = self.qty

        return actions


@dataclass
class Cooldown:
    max_consecutive_losses: int = 2
    cooldown_sec: int = 300
    losses: int = 0
    resume_ts: int = 0

    def on_trade_close(self, pnl: float, now_ts: int) -> None:
        if pnl < 0:
            self.losses += 1
            if self.losses >= self.max_consecutive_losses:
                self.resume_ts = max(self.resume_ts, now_ts + self.cooldown_sec)
        else:
            self.losses = 0

    def can_trade(self, now_ts: int) -> bool:
        if self.resume_ts and now_ts < self.resume_ts:
            return False
        return True

