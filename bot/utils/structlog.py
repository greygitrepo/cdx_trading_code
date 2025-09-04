from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


@dataclass
class BaseEvent:
    ts: int
    run_id: str
    step: str  # e.g., signal | order | fill | pnl | cancel | risk | info
    symbol: Optional[str] = None
    meta: Optional[dict[str, Any]] = None

    def to_jsonl(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False)


class StructLogger:
    def __init__(self, run_dir: Path, run_id: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        _ensure_dir(run_dir)
        self.events_fp = run_dir / "events.jsonl"

    def _write(self, event: BaseEvent) -> None:
        with self.events_fp.open("a", encoding="utf-8") as f:
            f.write(event.to_jsonl() + "\n")

    # Signal scoring and decision
    def log_signal(
        self, *, ts: int, symbol: str, scores: dict[str, Any], decision: Optional[str]
    ) -> None:
        self._write(
            BaseEvent(
                ts=ts,
                run_id=self.run_id,
                step="signal",
                symbol=symbol,
                meta={"scores": scores, "decision": decision},
            )
        )

    # Order intent and placement result
    def log_order(
        self,
        *,
        ts: int,
        symbol: str,
        plan: dict[str, Any],
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        self._write(
            BaseEvent(
                ts=ts,
                run_id=self.run_id,
                step="order",
                symbol=symbol,
                meta={"plan": plan, "result": result},
            )
        )

    # Fill/Execution details
    def log_fill(
        self,
        *,
        ts: int,
        symbol: str,
        side: str,
        price: float,
        qty: float,
        order_id: Optional[str] = None,
    ) -> None:
        self._write(
            BaseEvent(
                ts=ts,
                run_id=self.run_id,
                step="fill",
                symbol=symbol,
                meta={"side": side, "price": price, "qty": qty, "order_id": order_id},
            )
        )

    # Cancel event
    def log_cancel(
        self,
        *,
        ts: int,
        symbol: str,
        order_link_id: Optional[str],
        reason: Optional[str] = None,
    ) -> None:
        self._write(
            BaseEvent(
                ts=ts,
                run_id=self.run_id,
                step="cancel",
                symbol=symbol,
                meta={"order_link_id": order_link_id, "reason": reason},
            )
        )

    # Risk checks outcome
    def log_risk(
        self,
        *,
        ts: int,
        symbol: Optional[str],
        ok: bool,
        reason: str,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        self._write(
            BaseEvent(
                ts=ts,
                run_id=self.run_id,
                step="risk",
                symbol=symbol,
                meta={"ok": ok, "reason": reason, "context": context or {}},
            )
        )

    # PnL snapshot (position close or periodic)
    def log_pnl(
        self,
        *,
        ts: int,
        symbol: str,
        realized: float,
        unrealized: Optional[float] = None,
    ) -> None:
        self._write(
            BaseEvent(
                ts=ts,
                run_id=self.run_id,
                step="pnl",
                symbol=symbol,
                meta={"realized": realized, "unrealized": unrealized},
            )
        )

    # Generic info hook (e.g., orderbook snapshot)
    def log_info(
        self, *, ts: int, symbol: Optional[str], tag: str, payload: dict[str, Any]
    ) -> None:
        self._write(
            BaseEvent(ts=ts, run_id=self.run_id, step=tag, symbol=symbol, meta=payload)
        )

    # Reasons for skipping/trade rejection at a step
    def log_why_no_trade(
        self,
        *,
        ts: int,
        symbol: str,
        reasons: list[str],
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        self._write(
            BaseEvent(
                ts=ts,
                run_id=self.run_id,
                step="why_no_trade",
                symbol=symbol,
                meta={"reasons": reasons, **(context or {})},
            )
        )


def init_run_dir(base_logs: Path, run_id: str) -> Path:
    run_dir = base_logs / run_id
    _ensure_dir(run_dir)
    return run_dir
