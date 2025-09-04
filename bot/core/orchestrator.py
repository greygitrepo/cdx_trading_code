"""Multi-symbol orchestrator with slot-based management.

Provides SlotManager and an orchestration helper to allocate budgets per symbol
and compute order quantities while preventing duplicates and respecting limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Iterable, Tuple
import json
from pathlib import Path
import os
import time

from bot.risk.position_sizer import compute_order_qty, SizedOrder
from bot.selector.symbol_selector import top_n


@dataclass
class PositionSlot:
    symbol: str
    state: str  # idle|entry|managed|closing
    entry_time: float
    ctx: Dict[str, object] = field(default_factory=dict)


class SlotManager:
    def __init__(self, max_slots: int) -> None:
        self.max_slots = max_slots
        self._slots: Dict[int, Optional[PositionSlot]] = {
            i: None for i in range(max_slots)
        }
        self._runtime_dir = _ensure_runtime_logs()

    def free_count(self) -> int:
        return sum(1 for v in self._slots.values() if v is None)

    def active_count(self) -> int:
        return sum(1 for v in self._slots.values() if v is not None)

    def current_symbols(self) -> Set[str]:
        return {v.symbol for v in self._slots.values() if v is not None}

    def acquire(self, symbol: str) -> Tuple[int, PositionSlot]:
        # Prevent duplicates
        if symbol in self.current_symbols():
            raise ValueError("symbol already managed")
        for i, v in self._slots.items():
            if v is None:
                slot = PositionSlot(
                    symbol=symbol, state="entry", entry_time=time.time()
                )
                self._slots[i] = slot
                pos_fp = self._runtime_dir / "positions.jsonl"
                log_jsonl(
                    pos_fp,
                    {
                        "ts": int(time.time() * 1000),
                        "event": "slot_acquired",
                        "slot": i,
                        "symbol": symbol,
                    },
                )
                return i, slot
        raise RuntimeError("no free slot")

    def release_symbol(self, symbol: str) -> None:
        for i, v in self._slots.items():
            if v is not None and v.symbol == symbol:
                self._slots[i] = None
                pos_fp = self._runtime_dir / "positions.jsonl"
                log_jsonl(
                    pos_fp,
                    {
                        "ts": int(time.time() * 1000),
                        "event": "slot_released",
                        "slot": i,
                        "symbol": symbol,
                    },
                )
                return

    def iter_slots(self) -> Iterable[Tuple[int, PositionSlot]]:
        for i, v in self._slots.items():
            if v is not None:
                yield i, v


def _ensure_runtime_logs() -> Path:
    base = Path("reports/runtime")
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_jsonl(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def resolve_total_budget_usdt(
    *,
    total_budget_env: Optional[float],
    total_budget_cfg: Optional[float],
    balance_free: Optional[float],
    use_balance_ratio: float = 1.0,
) -> float:
    # Priority: Env > Config > Balance * ratio
    if total_budget_env is not None:
        return float(total_budget_env)
    if total_budget_cfg is not None:
        return float(total_budget_cfg)
    if balance_free is not None:
        return float(balance_free) * float(max(0.0, min(use_balance_ratio, 1.0)))
    return 0.0


def safe_int_env(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return int(str(raw).split("#", 1)[0].strip())
    except Exception:
        return None


def safe_float_env(name: str) -> Optional[float]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return float(str(raw).split("#", 1)[0].strip())
    except Exception:
        return None


def compute_per_symbol_budget(
    total_budget_usdt: float, active: int, to_fill: int
) -> float:
    denom = max(1, active + to_fill)
    return max(0.0, total_budget_usdt / float(denom))


def plan_entries(
    *,
    symbols_ranked: List[str],
    slot_mgr: SlotManager,
    max_symbols: int,
    open_order_symbols: Set[str],
    position_symbols: Set[str],
    prices: Dict[str, float],
    leverage: float,
    rules: Dict[str, dict],  # {symbol: {lot_step, tick_size, min_qty, min_notional?}}
    total_budget_usdt: float,
) -> List[dict]:
    """Select symbols and compute qty/budget for entries; return order intents.

    Each result includes structured fields for downstream order placement and logging.
    """
    runtime_dir = _ensure_runtime_logs()
    orders_fp = runtime_dir / "orders.jsonl"

    exclude = slot_mgr.current_symbols() | open_order_symbols | position_symbols
    free_slots = min(
        max(0, max_symbols - slot_mgr.active_count()), slot_mgr.free_count()
    )
    # Fill only as many as free slots
    target: List[str] = []
    for s in symbols_ranked:
        if s in exclude:
            continue
        target.append(s)
        if len(target) >= free_slots:
            break

    per_budget = compute_per_symbol_budget(
        total_budget_usdt, slot_mgr.active_count(), len(target)
    )
    results: List[dict] = []
    for sym in target:
        px = prices.get(sym, 0.0)
        rule = rules.get(sym, {})
        sized: SizedOrder = compute_order_qty(
            px,
            per_budget,
            leverage=leverage,
            lot_step=rule.get("lot_step"),
            tick_size=rule.get("tick_size"),
            min_qty=rule.get("min_qty"),
            min_notional=rule.get("min_notional"),
        )
        acquired = slot_mgr.acquire(sym)
        try:
            slot_idx, _slot = acquired  # type: ignore[misc]
        except Exception:
            slot_idx = -1
        payload = {
            "symbol": sym,
            "slot": slot_idx,
            "budget_usdt": per_budget,
            "price": px,
            "qty": sized.qty,
            "est_notional": sized.est_notional,
            "used_budget": sized.used_budget,
        }
        log_jsonl(
            orders_fp, {"ts": int(time.time() * 1000), "event": "entry_plan", **payload}
        )
        results.append(payload)
    return results


class Orchestrator:
    """Lightweight loop orchestrator for ops smoke tests.

    Requires an exchange client exposing:
      - position_symbols() -> list[str]
      - open_order_symbols() -> list[str]
      - get_mark_price(symbol) -> float
      - get_market_rules(symbol) -> object with lot_step, tick_size, min_qty?
      - place_order(symbol, side, qty, price=None, reduce_only=False)
      - close_position(symbol)
    """

    def __init__(
        self,
        *,
        ex,
        slot_mgr: SlotManager,
        leverage: float = 5.0,
        max_symbols: int = 5,
        total_budget_usdt: Optional[float] = None,
    ) -> None:
        self.ex = ex
        self.slot_mgr = slot_mgr
        self.leverage = leverage
        self.max_symbols = max(1, min(int(max_symbols or 5), 10))
        self.total_budget_usdt = total_budget_usdt
        self.runtime = _ensure_runtime_logs()

    def _resolve_budget(self) -> float:
        env_total = safe_float_env("TOTAL_BUDGET_USDT")
        cfg_total = self.total_budget_usdt
        # Exchange free balance is not fetched here; ops tests may pass explicit budget
        return resolve_total_budget_usdt(
            total_budget_env=env_total,
            total_budget_cfg=cfg_total,
            balance_free=None,
            use_balance_ratio=float(os.getenv("RISK_USE_BALANCE_RATIO", "1.0")),
        )

    def run_loop(
        self,
        *,
        max_ticks: int = 1,
        bootstrap_candidates: Optional[List[str]] = None,
        backoff_max: int = 2,
    ) -> None:
        budget_total = self._resolve_budget() or 1000.0
        defaults = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]
        candidates = bootstrap_candidates[:] if bootstrap_candidates else defaults
        for _ in range(max(1, max_ticks)):
            # Determine exclude set
            try:
                exclude = (
                    set(self.ex.position_symbols())
                    | set(self.ex.open_order_symbols())
                    | self.slot_mgr.current_symbols()
                )
            except Exception:
                exclude = self.slot_mgr.current_symbols()
            cands = top_n(candidates, self.max_symbols, exclude_symbols=exclude)
            free_slots = min(
                self.max_symbols - self.slot_mgr.active_count(),
                self.slot_mgr.free_count(),
            )
            target = cands[: max(0, free_slots)]
            per_budget = compute_per_symbol_budget(
                budget_total, self.slot_mgr.active_count(), len(target)
            )
            for sym in target:
                # Try/fallback with simple backoff on transient errors
                attempt = 0
                while True:
                    try:
                        px = float(self.ex.get_mark_price(sym))
                        rule = self.ex.get_market_rules(sym)
                        sized = compute_order_qty(
                            px,
                            per_budget,
                            leverage=self.leverage,
                            lot_step=getattr(rule, "lot_step", None),
                            tick_size=getattr(rule, "tick_size", None),
                            min_qty=getattr(rule, "min_qty", None),
                        )
                        self.slot_mgr.acquire(sym)
                        # For smoke, just place a tiny buy and immediately reduce-only close
                        q = max(getattr(rule, "lot_step", 0.001) or 0.001, sized.qty)
                        self.ex.place_order(sym, "buy", q)
                        # Immediate clean-up to avoid lingering state
                        try:
                            self.ex.close_position(sym)
                        except Exception:
                            pass
                        break
                    except Exception:
                        if attempt >= backoff_max:
                            # Log and continue next symbol
                            log_jsonl(
                                self.runtime / "orders.jsonl",
                                {
                                    "ts": int(time.time() * 1000),
                                    "event": "error",
                                    "symbol": sym,
                                    "attempt": attempt,
                                },
                            )
                            break
                        attempt += 1
                        time.sleep(0.1 * (2**attempt))
