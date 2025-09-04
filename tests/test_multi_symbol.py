from __future__ import annotations

import json
from pathlib import Path
import pytest

from bot.selector.symbol_selector import top_n
from bot.core.slot_manager import SlotManager
from bot.core.orchestrator import plan_entries, compute_per_symbol_budget


def read_jsonl(fp: Path) -> list[dict]:
    if not fp.exists():
        return []
    return [
        json.loads(line)
        for line in fp.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.unit
def test_selector_excludes_and_topn():
    ranked = [f"S{i}USDT" for i in range(1, 11)]
    exclude = {"S2USDT", "S4USDT", "S6USDT"}
    sel = top_n(ranked, 3, exclude_symbols=exclude)
    assert sel == ["S1USDT", "S3USDT", "S5USDT"]


@pytest.mark.unit
def test_budget_split_and_qty_rounding(tmp_path: Path, monkeypatch):
    # Setup runtime logs dir under tmp to avoid polluting repo
    rtdir = tmp_path / "reports/runtime"
    monkeypatch.chdir(tmp_path)
    # MAX_SYMBOLS=5, TOTAL_BUDGET_USDT=1000 -> 200 per new/active slot
    mgr = SlotManager(max_slots=5)
    symbols_ranked = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    open_orders = set()
    positions = set()
    prices = {s: 100.0 for s in symbols_ranked}
    leverage = 5.0
    rules = {
        s: {"lot_step": 0.001, "tick_size": 0.01, "min_qty": 0.001}
        for s in symbols_ranked
    }
    intents = plan_entries(
        symbols_ranked=symbols_ranked,
        slot_mgr=mgr,  # SlotManager from slot_manager works via orchestrator interface
        max_symbols=5,
        open_order_symbols=open_orders,
        position_symbols=positions,
        prices=prices,
        leverage=leverage,
        rules=rules,
        total_budget_usdt=1000.0,
    )
    # Expect 5 items and each approx notional ~ budget*lev = 200*5=1000 at price 100 -> qty ~ 10, rounded
    assert len(intents) == 5
    for it in intents:
        assert it["budget_usdt"] == 1000.0 / 5.0
        assert abs(it["qty"] - 10.0) < 1e-6

    # Verify JSONL log exists
    orders_fp = rtdir / "orders.jsonl"
    rows = read_jsonl(orders_fp)
    assert len(rows) == 5
    for r in rows:
        assert r["event"] == "entry_plan"
        assert r["symbol"] in symbols_ranked


@pytest.mark.unit
def test_min_qty_and_slot_lifecycle(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = SlotManager(max_slots=3)
    # Pre-occupy one slot to simulate existing position
    mgr.acquire("BTCUSDT")
    assert mgr.active_count() == 1
    symbols_ranked = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    # BTCUSDT should be excluded; pick ETH, SOL for 2 free slots
    open_orders = set()
    positions = {"BTCUSDT"}
    prices = {s: 200.0 for s in symbols_ranked}
    rules = {
        s: {"lot_step": 0.05, "tick_size": 0.01, "min_qty": 1.0} for s in symbols_ranked
    }
    intents = plan_entries(
        symbols_ranked=symbols_ranked,
        slot_mgr=mgr,
        max_symbols=3,
        open_order_symbols=open_orders,
        position_symbols=positions,
        prices=prices,
        leverage=10.0,
        rules=rules,
        total_budget_usdt=600.0,  # active 1 + to_fill 2 => denom 3 => per 200
    )
    # Should fill 2 new symbols (ETH, SOL), skip BTC
    syms = [it["symbol"] for it in intents]
    assert syms == ["ETHUSDT", "SOLUSDT"]
    # qty = (200*10)/200=10 -> rounded to step 0.05 -> 10.0, min_qty=1 enforced implicitly
    for it in intents:
        assert abs(it["qty"] - 10.0) < 1e-9
    # Release a slot and ensure counts
    mgr.release("BTCUSDT")
    assert mgr.active_count() == 2


@pytest.mark.unit
def test_compute_per_symbol_budget():
    # When active=2 and to_fill=3, denom=5
    budget = compute_per_symbol_budget(1000.0, 2, 3)
    assert budget == 200.0
