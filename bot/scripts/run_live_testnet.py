"""Run live testnet loop for Bybit v5 with basic risk checks.

ENV toggles expected:
- STUB_MODE=false, PAPER_MODE=false, LIVE_MODE=true, TESTNET=true
- BYBIT_API_KEY, BYBIT_API_SECRET
- BYBIT_SYMBOL, BYBIT_CATEGORY, LEVERAGE, MAX_ALLOC_PCT, MIN_FREE_BALANCE_USDT

This script performs:
1) API key validation via wallet balance
2) Fetch orderbook and last mid
3) Build a tiny order plan from a dummy signal (+1 then immediate cancel)
4) Place/cancel order and log structured events

Set DRY_RUN=true to simulate without sending orders.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path as _P
from typing import Any

# Ensure repo root on path
_ROOT = _P(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot.core.exchange.bybit_v5 import BybitV5Client, BybitAPIError  # noqa: E402
from bot.core.execution.risk_rules import RiskContext, check_balance_guard, check_order_size, slippage_guard  # noqa: E402
from bot.core.strategy_runner import build_order_plan  # noqa: E402


def setup_loggers() -> tuple[logging.Logger, _P]:
    logs_dir = _P("logs/live_testnet")
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("live_testnet")
    logger.setLevel(logging.INFO)
    # Rotating file handler (simple size-based)
    fh = logging.FileHandler(logs_dir / "app.log")
    fh.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    if not logger.handlers:
        logger.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger, logs_dir


def write_event(logs_dir: _P, event: dict[str, Any]) -> None:
    fp = logs_dir / "events.jsonl"
    with fp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def require_env_flags(logger: logging.Logger) -> None:
    flags = {
        "STUB_MODE": os.environ.get("STUB_MODE", "false").lower(),
        "PAPER_MODE": os.environ.get("PAPER_MODE", "false").lower(),
        "LIVE_MODE": os.environ.get("LIVE_MODE", "true").lower(),
        "TESTNET": os.environ.get("TESTNET", "true").lower(),
    }
    logger.info(f"Env flags: {flags}")
    if not (flags["LIVE_MODE"] == "true" and flags["TESTNET"] == "true"):
        logger.warning("LIVE_MODE must be true and TESTNET true for this script")


def main() -> None:
    logger, logs_dir = setup_loggers()
    require_env_flags(logger)
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    client = BybitV5Client()
    symbol = os.environ.get("BYBIT_SYMBOL", "BTCUSDT")
    category = os.environ.get("BYBIT_CATEGORY", "linear")

    # 1) API key validation
    try:
        wb = client.get_wallet_balance()
        logger.info("Wallet balance call OK: retCode=0")
        write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "wallet_balance", "data": wb.get("result", {})})
    except BybitAPIError as e:
        logger.error(f"Wallet balance failed: {e}")
        sys.exit(2)

    # Extract equity and free balance (best effort)
    equity = 0.0
    free = 0.0
    try:
        acct = wb.get("result", {}).get("list", [{}])[0]
        total_equity = float(acct.get("totalEquity", 0)) if "totalEquity" in acct else 0.0
        equity = total_equity
        # Free simplified: availableToWithdraw if present
        free = float(acct.get("totalAvailableBalance") or acct.get("availableToWithdraw") or 0)
    except Exception:
        pass
    logger.info(f"Equity={equity:.2f} USDT, Free={free:.2f} USDT")

    # 2) Get orderbook and infer mid price
    ob = client.get_orderbook(symbol=symbol, depth=1, category=category)
    write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "orderbook", "data": ob.get("result", {})})
    try:
        bids = ob["result"]["b"]
        asks = ob["result"]["a"]
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid = (best_bid + best_ask) / 2
    except Exception:
        logger.error("Failed to parse orderbook; aborting")
        sys.exit(3)
    logger.info(f"L1 mid={mid:.2f} for {symbol}")

    # 3) Build a dummy long signal (+1) plan
    plan = build_order_plan(signal=+1, last_price=mid, equity_usdt=equity, symbol=symbol)
    logger.info(
        f"OrderPlan: side={plan.side} qty={plan.qty:.6f} type={plan.order_type} tif={plan.tif} tp={plan.tp:.2f} sl={plan.sl:.2f}"
    )

    # Risk checks
    ok, reason = check_balance_guard(RiskContext(equity_usdt=equity, free_usdt=free, symbol=symbol, last_mid=mid))
    if not ok:
        logger.warning(f"Risk blocked (balance): {reason}")
        return
    notional = plan.qty * mid  # linear USDT perp approx
    ok, reason = check_order_size(notional, equity)
    if not ok:
        logger.warning(f"Risk blocked (size): {reason}")
        return
    if plan.order_type == "Limit" and plan.price is not None:
        ok, reason = slippage_guard(plan.price, mid)
        if not ok:
            logger.warning(f"Risk blocked (slippage): {reason}")
            return

    if dry_run:
        logger.info("DRY_RUN=true; skipping actual order placement")
        return

    # 4) Place order then cancel for smoke test
    try:
        res = client.place_order(
            symbol=plan.symbol,
            side=plan.side,
            qty=str(round(plan.qty, 6)),
            orderType=plan.order_type,
            timeInForce=plan.tif,
            price=str(plan.price) if plan.price is not None else None,
            orderLinkId=plan.order_link_id,
            takeProfit=str(plan.tp) if plan.tp else None,
            stopLoss=str(plan.sl) if plan.sl else None,
        )
        write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "order_create", "data": res})
        logger.info("Order placed")
    except BybitAPIError as e:
        logger.error(f"Place order failed: {e}")
        return

    # Fetch open orders
    try:
        oo = client.get_open_orders(symbol=symbol)
        write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "open_orders", "data": oo})
    except BybitAPIError as e:
        logger.warning(f"Open orders fetch failed: {e}")

    # Cancel by orderLinkId
    try:
        cres = client.cancel_order(symbol=symbol, orderLinkId=plan.order_link_id)
        write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "order_cancel", "data": cres})
        logger.info("Order cancel sent")
    except BybitAPIError as e:
        logger.error(f"Cancel failed: {e}")


if __name__ == "__main__":
    main()

