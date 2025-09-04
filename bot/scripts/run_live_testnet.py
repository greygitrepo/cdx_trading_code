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
from bot.core.strategies import StrategyParams, mis_signal, vrs_signal, lsr_signal, select_strategy  # noqa: E402
from bot.core.indicators import Rolling  # noqa: E402
try:
    from bot.core.exchange.bybit_ws import BybitPrivateWS  # type: ignore # noqa: E402
except Exception:  # noqa: BLE001
    BybitPrivateWS = None  # type: ignore


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
    leverage = float(os.environ.get("LEVERAGE", "10"))
    enable_ws = os.environ.get("ENABLE_PRIVATE_WS", "false").lower() == "true"
    # Regime/signal thresholds
    spread_threshold = float(os.environ.get("MIS_SPREAD_THRESHOLD", "0.0004"))
    spread_pause_mult = float(os.environ.get("SPREAD_PAUSE_MULT", "3.0"))
    min_depth_usd = float(os.environ.get("MIN_DEPTH_USD", "15000"))

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

    # 1.5) Load instrument filters & set leverage
    try:
        ins = client.get_instruments(category=category)
        flt = client.extract_symbol_filters(ins, symbol)
        logger.info(
            f"Instrument filters for {symbol}: tickSize={flt.get('tickSize')} qtyStep={flt.get('qtyStep')} minQty={flt.get('minOrderQty')}"
        )
    except Exception as e:
        logger.warning(f"Failed to fetch instrument filters: {e}")
        flt = {"tickSize": None, "qtyStep": None, "minOrderQty": None}

    try:
        client.set_leverage(symbol=symbol, buyLeverage=int(leverage), sellLeverage=int(leverage), category=category)
        logger.info("Leverage set OK")
    except BybitAPIError as e:
        logger.warning(f"Set leverage failed: {e}")

    # Optional: start private WS for live event logging
    ws = None
    if enable_ws and BybitPrivateWS is not None:
        def _on_ws_msg(msg: dict[str, Any]) -> None:
            write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "ws", "data": msg})

        def _on_ws_err(err: Exception) -> None:
            logger.warning(f"WS error: {err}")

        try:
            ws = BybitPrivateWS(on_message=_on_ws_msg, on_error=_on_ws_err)
            ws.start()
            logger.info("Private WS started (order/execution/position)")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Private WS failed to start: {e}")

    # 2) Timed loop: signal -> order -> reflect -> cancel (smoke)
    loop_interval = float(os.environ.get("LOOP_INTERVAL_SEC", "5"))
    max_iters = int(os.environ.get("MAX_ITERS", "3"))
    mids: list[float] = []
    closes = Rolling(maxlen=120)
    vols = Rolling(maxlen=120)

    for i in range(max_iters):
        ob = client.get_orderbook(symbol=symbol, depth=1, category=category)
        write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "orderbook", "data": ob.get("result", {})})
        try:
            bids = ob["result"]["b"]
            asks = ob["result"]["a"]
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            bid_sz = float(bids[0][1]) if len(bids[0]) > 1 else 0.0
            ask_sz = float(asks[0][1]) if len(asks[0]) > 1 else 0.0
            mid = (best_bid + best_ask) / 2
            spread = (best_ask - best_bid) / mid if mid > 0 else 0.0
            obi = (bid_sz - ask_sz) / (bid_sz + ask_sz) if (bid_sz + ask_sz) > 0 else 0.0
        except Exception:
            logger.warning("Failed to parse orderbook; skipping iteration")
            time.sleep(loop_interval)
            continue
        mids.append(mid)
        closes.add(mid)
        vols.add(max(0.0, bid_sz + ask_sz))
        if len(mids) > 50:
            mids.pop(0)
        logger.info(f"[{i+1}/{max_iters}] mid={mid:.2f} spread={spread:.5f} obi={obi:.2f}")

        # Regime pause checks (liquidity/spread)
        if spread >= spread_threshold * spread_pause_mult or (bid_sz + ask_sz) * mid < min_depth_usd:
            logger.info("Regime=PAUSE (wide spread or low depth); sleeping")
            time.sleep(loop_interval)
            continue

        # 3) Strategy pack scoring (MIS/VRS/LSR) and selection
        sp = StrategyParams()
        mis = mis_signal(closes.list(), orderbook_imbalance=(obi + 1) / 2, spread=spread, spread_threshold=spread_threshold, params=sp)
        vrs = vrs_signal(closes.list(), vols.list(), sp)
        # Heuristic for LSR inputs
        wick_long = False
        trade_burst = (bid_sz + ask_sz) > 0 and vols.list() and (bid_sz + ask_sz) > 2.0 * max(1e-9, vols.list()[-1])
        oi_drop = False  # not available without OI feed
        lsr = lsr_signal(wick_long=wick_long, trade_burst=trade_burst, oi_drop=oi_drop)
        strat_name, strat_side = select_strategy(mis, vrs, lsr)
        if strat_name is None or strat_side is None:
            logger.info("No strategy consensus; sleeping")
            time.sleep(loop_interval)
            continue
        signal = +1 if str(strat_side) == "Side.BUY" or strat_side == "BUY" else -1
        logger.info(f"Strategy selected: {strat_name} -> {('BUY' if signal>0 else 'SELL')}")

        prefer_limit = spread <= 0.0005
        # Avoid taker near funding if configured and nextFundingTime is close
        try:
            avoid_min = float(os.environ.get("AVOID_TAKER_WITHIN_MIN", "5"))
            if not prefer_limit and avoid_min > 0:
                tk = client.get_tickers(category=category, symbol=symbol)
                nxt = tk.get("result", {}).get("list", [{}])[0].get("nextFundingTime")
                if nxt:
                    now_ms = int(time.time() * 1000)
                    rem_min = max(0.0, (float(nxt) - now_ms) / 60000.0)
                    if rem_min <= avoid_min:
                        logger.info(f"Within {avoid_min}m of funding; skip taker")
                        time.sleep(loop_interval)
                        continue
        except Exception:
            pass
        plan = build_order_plan(
            signal=signal,
            last_price=mid,
            equity_usdt=equity,
            symbol=symbol,
            leverage=leverage,
            price_tick=flt.get("tickSize"),
            qty_step=flt.get("qtyStep"),
            min_qty=flt.get("minOrderQty"),
            prefer_limit=prefer_limit,
            post_only=prefer_limit,
        )
        logger.info(
            f"OrderPlan: side={plan.side} qty={plan.qty:.6f} type={plan.order_type} tif={plan.tif} tp={plan.tp:.2f} sl={plan.sl:.2f}"
        )

        # Risk checks
        ok, reason = check_balance_guard(RiskContext(equity_usdt=equity, free_usdt=free, symbol=symbol, last_mid=mid))
        if not ok:
            logger.warning(f"Risk blocked (balance): {reason}")
            break
        notional = plan.qty * mid
        ok, reason = check_order_size(notional, equity)
        if not ok:
            logger.warning(f"Risk blocked (size): {reason}")
            time.sleep(loop_interval)
            continue
        if plan.order_type == "Limit" and plan.price is not None:
            ok, reason = slippage_guard(plan.price, mid)
            if not ok:
                logger.warning(f"Risk blocked (slippage): {reason}")
                time.sleep(loop_interval)
                continue

        if dry_run:
            logger.info("DRY_RUN=true; skipping actual order placement this iteration")
            time.sleep(loop_interval)
            continue

        # 4) Place order and then cancel for smoke
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
            time.sleep(loop_interval)
            continue

        # Reflect open orders and positions
        try:
            oo = client.get_open_orders(symbol=symbol)
            write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "open_orders", "data": oo})
        except BybitAPIError as e:
            logger.warning(f"Open orders fetch failed: {e}")

        try:
            pos = client.get_positions(category=category, symbol=symbol)
            write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "positions", "data": pos})
            # Time stop and trailing if position present
            plist = pos.get("result", {}).get("list", [])
            if plist:
                p = plist[0]
                size = abs(float(p.get("size") or 0))
                side_long = (p.get("side") == "Buy")
                avg_price = float(p.get("avgPrice") or 0)
                # Simple trailing: if price moved favorably by trail_after_tp1, set trailingStop
                trail_after = float(os.environ.get("TRAIL_AFTER_TP1_PCT", "0.0008"))
                tp_pct = float(os.environ.get("TP_PCT", "0.0010"))
                sl_pct = float(os.environ.get("SL_PCT", "0.0020"))
                if size > 0 and avg_price > 0:
                    move = (mid - avg_price) / avg_price if side_long else (avg_price - mid) / avg_price
                    if move >= trail_after:
                        try:
                            trailing_abs = round(avg_price * sl_pct, 4)
                            client.set_trading_stop(
                                symbol=symbol,
                                trailingStop=trailing_abs,
                                takeProfit=avg_price * (1 + tp_pct if side_long else 1 - tp_pct),
                                stopLoss=avg_price * (1 - sl_pct if side_long else 1 + sl_pct),
                                category=category,
                            )
                            logger.info("Applied trailing stop via trading-stop API")
                        except BybitAPIError as e:
                            logger.warning(f"Trailing stop set failed: {e}")
                # Time stop: close if holding longer than threshold
                time_stop_sec = int(os.environ.get("TIME_STOP_SEC", "1200"))
                et = p.get("updatedTime") or p.get("createdTime")  # ms
                if size > 0 and et is not None:
                    held_sec = max(0, int((int(time.time() * 1000) - int(et)) / 1000))
                    if held_sec >= time_stop_sec:
                        try:
                            qty = size
                            side = "SELL" if side_long else "BUY"
                            client.close_position_market(symbol=symbol, side=side, qty=str(qty), category=category)
                            logger.info(f"Time stop triggered after {held_sec}s; closing position")
                        except BybitAPIError as e:
                            logger.warning(f"Time stop close failed: {e}")
        except BybitAPIError as e:
            logger.warning(f"Positions fetch failed: {e}")

        # Try to cancel by orderLinkId for smoke
        try:
            cres = client.cancel_order(symbol=symbol, orderLinkId=plan.order_link_id)
            write_event(logs_dir, {"ts": int(time.time() * 1000), "type": "order_cancel", "data": cres})
            logger.info("Order cancel sent")
        except BybitAPIError as e:
            logger.error(f"Cancel failed: {e}")

        time.sleep(loop_interval)

    # Graceful WS shutdown if enabled
    try:
        if enable_ws and 'ws' in locals() and ws is not None:
            ws.stop()
    except Exception:
        pass


if __name__ == "__main__":
    main()
