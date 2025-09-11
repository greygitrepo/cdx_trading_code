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

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path as _P
from typing import Any
import argparse
import datetime as _dt

try:
    from bot.core.exchange.bybit_v5 import BybitV5Client, BybitAPIError
    from bot.core.execution.risk_rules import (
        RiskContext,
        check_balance_guard,
        check_order_size,
        slippage_guard,
    )
    from bot.core.strategy_runner import build_order_plan
    from bot.core.strategies import (
        StrategyParams,
        mis_signal,
        vrs_signal,
        lsr_signal,
        select_strategy,
    )
    from bot.core.indicators import Rolling
    from bot.core.signals.obflow import decide as obflow_decide, OBFlowConfig
    from bot.core.config import load_runtime
    from bot.core.rotation import build_universe, ExitFlag
    from bot.core.ledger import TradeLedger
    from bot.app.runners.live_runner import LiveRunner
    from bot.app.wiring import AppContext as _AppCtx
    from bot.utils.structlog import StructLogger, init_run_dir
    from bot.core.event_bus import EventBus
    from bot.core.order_router import OrderRouter
    from bot.core.market_data_hub import MarketDataHub
    from bot.actors.symbol_actor import SymbolActor
    from bot.app.runners.live_testnet_runner import (
        setup_loggers,
        write_event,
        require_env_flags,
        load_dotenv_if_present,
        LiveTestnetOrchestrator,
    )
except Exception:  # pragma: no cover - fallback for direct script runs
    _ROOT = _P(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from bot.core.exchange.bybit_v5 import BybitV5Client, BybitAPIError
    from bot.core.execution.risk_rules import (
        RiskContext,
        check_balance_guard,
        check_order_size,
        slippage_guard,
    )
    from bot.core.strategy_runner import build_order_plan
    from bot.core.strategies import (
        StrategyParams,
        mis_signal,
        vrs_signal,
        lsr_signal,
        select_strategy,
    )
    from bot.core.indicators import Rolling
    from bot.core.signals.obflow import decide as obflow_decide, OBFlowConfig
    from bot.core.config import load_runtime
    from bot.core.rotation import build_universe, ExitFlag
    from bot.utils.structlog import StructLogger, init_run_dir
    from bot.core.event_bus import EventBus
    from bot.core.order_router import OrderRouter
    from bot.core.market_data_hub import MarketDataHub
    from bot.actors.symbol_actor import SymbolActor
    from bot.core.ledger import TradeLedger
    from bot.app.runners.live_testnet_runner import (
        setup_loggers,
        write_event,
        require_env_flags,
        load_dotenv_if_present,
        LiveTestnetOrchestrator,
    )
    from bot.app.runners.live_runner import LiveRunner
    from bot.app.wiring import AppContext as _AppCtx

import yaml  # type: ignore

try:
    from bot.core.exchange.bybit_ws import BybitPrivateWS  # type: ignore # noqa: E402
except Exception:  # noqa: BLE001
    BybitPrivateWS = None  # type: ignore

# Reporting (optional trade ledger per-run)
try:
    from bot.core.reporting.writer import TradeLedgerWriter  # type: ignore # noqa: E402
    from bot.core.reporting.ledger import TradeLedgerRow  # type: ignore # noqa: E402
except Exception:
    TradeLedgerWriter = None  # type: ignore
    TradeLedgerRow = None  # type: ignore


    # helper defs moved to app.runners.live_testnet_runner


async def _actor_main(args) -> None:
    symbols = (
        args.symbols.split(",") if args.symbols else [os.environ.get("BYBIT_SYMBOL", "BTCUSDT")]
    )
    rate_limit = 3
    run_id = f"run_{_dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    logger, _ = setup_loggers(run_id)
    logger.info(f"ActorMode=on symbols={symbols} rate_limit={rate_limit}")
    bus = EventBus()
    client = BybitV5Client()
    router = OrderRouter(client, asyncio.Semaphore(rate_limit))

    async def _dummy_source():
        while True:
            await asyncio.sleep(3600)
            yield {}

    hub = MarketDataHub(_dummy_source(), bus)
    cfg = {"risk": {"qty": 1}, "min_edge": 0}
    actors = [SymbolActor(sym, cfg, bus, router) for sym in symbols]
    tasks = [asyncio.create_task(hub.run(symbols))]
    tasks.extend(asyncio.create_task(a.run()) for a in actors)

    async def _sla_logger():
        while True:
            logger.info(
                "avg_per_symbol_sla_ms=0 p95_decision_to_order_ms=0 stale_events=0 dup_idem=0"
            )
            await asyncio.sleep(5)

    tasks.append(asyncio.create_task(_sla_logger()))
    await asyncio.gather(*tasks)


def main() -> None:
    # CLI
    parser = argparse.ArgumentParser(description="Run Bybit v5 live testnet loop")
    parser.add_argument(
        "--profile",
        default=os.environ.get("PROFILE", ""),
        help="profile name (e.g., quick-test)",
    )
    parser.add_argument(
        "--strategy",
        default=os.environ.get("STRATEGY", "obflow"),
        help="Strategy name registered in registry (default: obflow)",
    )
    parser.add_argument(
        "--strategy-param",
        action="append",
        default=[],
        help="Override strategy param as k=v (can repeat)",
    )
    parser.add_argument(
        "--actor-mode",
        action="store_true",
        default=False,
        help="enable async actor mode",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="comma separated symbols",
    )
    args = parser.parse_args()

    if args.actor_mode:
        asyncio.run(_actor_main(args))
        return

    # Run ID and loggers
    run_id = f"run_{_dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    logger, logs_dir = setup_loggers(run_id)
    # Load .env if present (no override)
    n_loaded = load_dotenv_if_present()
    if n_loaded:
        logger.info(f"Loaded {n_loaded} vars from .env")
    slog = StructLogger(logs_dir, run_id)
    ledger = TradeLedger(run_id=run_id, out_dir=_P("reports"))
    # Optional per-trade ledger writer (CSV/JSONL under logs/run_<RUN_ID>)
    tle_enabled = os.environ.get("TRADE_LEDGER_ENABLED", "true").strip().lower() == "true"
    tle_formats = [s.strip() for s in os.environ.get("TRADE_LEDGER_FORMATS", "csv,jsonl").split(",") if s.strip()]
    tl_writer = None
    if tle_enabled and TradeLedgerWriter is not None:
        tl_writer = TradeLedgerWriter(run_id, str(logs_dir))
    require_env_flags(logger)
    # Load YAML (single source) and export key params into ENV with precedence: YAML > ENV > Defaults
    runtime = load_runtime()
    # Apply CLI strategy selection into AppConfig (preserve existing defaults)
    cli_strategy = (args.strategy or "").strip()
    if cli_strategy:
        try:
            runtime.app.strategy.name = cli_strategy
        except Exception:
            pass
    # Parse repeated --strategy-param k=v into dict
    sp: dict[str, str] = {}
    for item in (args.strategy_param or []):
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        sp[k.strip()] = v.strip()
    try:
        # Merge params with precedence: CLI > YAML
        merged = dict(getattr(runtime.app.strategy, "params", {}) or {})
        merged.update(sp)
        runtime.app.strategy.params = merged
    except Exception:
        pass
    # Build and write strategy header for reproducibility
    LiveTestnetOrchestrator.emit_strategy_header(runtime.app, logs_dir, run_id)
    LiveTestnetOrchestrator.export_resolved_from_yaml(runtime, logger, slog)
    # Load profile config if requested (pure YAML overlay; then re-export to ENV)
    if args.profile:
        try:
            prof_name = "quick_test" if args.profile == "quick-test" else args.profile
            prof_path = _P(f"bot/configs/profiles/{prof_name}.yaml")
            if prof_path.exists():
                if LiveTestnetOrchestrator.apply_profile_overlay(runtime, args.profile, logger):
                    LiveTestnetOrchestrator.export_resolved_from_yaml(runtime, logger, slog)
            else:
                logger.warning(f"Profile not found: {prof_path}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Profile load failed: {e}")
    require_env_flags(logger)
    # Safety: default DRY_RUN=true unless explicitly false
    if "DRY_RUN" not in os.environ:
        os.environ["DRY_RUN"] = "true"
    dry_run = os.environ.get("DRY_RUN", "true").lower() == "true"

    client = BybitV5Client()
    symbol = os.environ.get("BYBIT_SYMBOL", "BTCUSDT")
    # Load YAML once
    runtime = load_runtime()
    category = str(getattr(runtime.app.exchange, 'category', 'linear'))
    ob_cfg = OBFlowConfig.from_params(runtime.params)
    ee = runtime.params.entry_exit
    obp = runtime.params.orderbook
    fund = runtime.params.funding_time
    execp = getattr(runtime.params, "execution", None)
    # Strategy selection precedence: CLI > ENV > config
    strategy = (args.strategy or runtime.app.strategy.name or "").strip().lower()
    if not strategy:
        strategy = os.environ.get("STRATEGY", "").strip().lower()
    if not strategy:
        try:
            strategy = str(getattr(runtime.app.runtime, "strategy", "pack")).lower()
        except Exception:
            strategy = "pack"
    os.environ["STRATEGY"] = strategy

    # Helpers to parse envs with inline comments (e.g., "7   # note")
    def _env_clean(name: str, default: str | float | int) -> str:
        raw = os.environ.get(name, str(default))
        return raw.split("#", 1)[0].strip()

    def _env_float(name: str, default: float) -> float:
        try:
            val = _env_clean(name, default)
            return float(val) if val != "" else float(default)
        except Exception:
            return float(default)

    def _env_int(name: str, default: int) -> int:
        try:
            val = _env_clean(name, default)
            return int(val) if val != "" else int(default)
        except Exception:
            return int(default)

    def _env_bool(name: str, default: bool) -> bool:
        val = _env_clean(name, "true" if default else "false").lower()
        return val == "true"

    def _position_mode() -> str:
        v = os.environ.get("POSITION_MODE", "ONEWAY").strip().upper()
        return v if v in {"ONEWAY", "HEDGE"} else "ONEWAY"

    def _position_idx_for_side(side: str, mode: str) -> int | None:
        if mode != "HEDGE":
            return None
        return 1 if str(side).upper() == "BUY" else 2

    def _fee_amount(notional: float, bps: float) -> float:
        try:
            return abs(float(notional)) * max(0.0, float(bps)) / 1e4
        except Exception:
            return 0.0

    def _fee_aware_targets(
        entry_price: float,
        *,
        side_long: bool,
        tp_net: float,
        sl_net: float,
        entry_fee_bps: float,
        exit_fee_bps: float,
    ) -> tuple[float, float]:
        fe = max(0.0, float(entry_fee_bps)) / 1e4
        fx = max(0.0, float(exit_fee_bps)) / 1e4
        fee_sum = fe + fx
        tp_gross = max(0.0, tp_net + fee_sum)
        sl_gross = max(0.0, sl_net - fee_sum)
        if side_long:
            return entry_price * (1 + tp_gross), entry_price * (1 - sl_gross)
        else:
            return entry_price * (1 - tp_gross), entry_price * (1 + sl_gross)

    def _round_to_tick(price: float, tick: float | None, *, up: bool | None = None) -> float:
        if not tick or tick <= 0:
            return price
        # Favorable rounding: up=True => ceil to tick, up=False => floor to tick, None => nearest down
        mult = price / tick
        if up is True:
            from math import ceil

            return ceil(mult) * tick
        if up is False:
            from math import floor

            return floor(mult) * tick
        from math import floor

        return floor(mult) * tick

    leverage = float(getattr(runtime.app.risk, 'max_leverage', 10))
    enable_ws = _env_bool("ENABLE_PRIVATE_WS", False)
    # Fee rates (bps); will try API first, then fallback to env/defaults
    maker_fee_bps = 2.0
    taker_fee_bps = 5.5
    fee_assume_entry = os.environ.get("FEE_ASSUME_ENTRY", "auto").lower()  # auto|maker|taker
    fee_assume_exit = os.environ.get("FEE_ASSUME_EXIT", "taker").lower()   # maker|taker
    # Regime/signal thresholds (YAML)
    spread_threshold = float(getattr(runtime.params.universe, 'spread_threshold_pct', 0.0004))
    spread_pause_mult = float(getattr(runtime.params.regime, 'spread_mult_pause', 3.0))
    min_depth_usd = float(getattr(obp, "min_depth_usd", 5000.0))

    # Helper: adapt internal TradeRecord -> reporting.TradeLedgerRow
    def _build_row_from_rec(run_id_val, rec) -> TradeLedgerRow:  # type: ignore[valid-type]
        def pct(x):
            try:
                return float(x) * 100.0
            except Exception:
                return 0.0
        return TradeLedgerRow(
            trade_id=f"{run_id_val}:{rec.symbol}:{rec.entry_time}",
            run_id=run_id_val,
            symbol=rec.symbol,
            side=rec.side,  # LONG/SHORT
            entry_time=int(rec.entry_time),
            entry_price=float(rec.entry_price),
            entry_qty=float(rec.entry_qty),
            entry_value_usdt=float(rec.entry_value_usdt),
            entry_liquidity=(rec.entry_liquidity if rec.entry_liquidity in ("maker", "taker") else None),
            entry_fee_usdt=float(rec.entry_fee_usdt),
            entry_slippage_pct=pct(rec.entry_slippage_pct),
            exit_time=int(rec.exit_time or 0),
            exit_price=float(rec.exit_price or 0.0),
            exit_qty=float(rec.exit_qty or 0.0),
            exit_value_usdt=float(rec.exit_value_usdt or 0.0),
            exit_liquidity=(rec.exit_liquidity if rec.exit_liquidity in ("maker", "taker") else None),
            exit_fee_usdt=float(rec.exit_fee_usdt or 0.0),
            exit_slippage_pct=pct(rec.exit_slippage_pct or 0.0),
            exit_reason=str(rec.exit_reason or "MANUAL"),
            hold_secs=float(rec.hold_secs or 0),
            realized_pnl_usdt=float(rec.realized_pnl_usdt),
            realized_pnl_pct_on_value=pct(rec.realized_pnl_usdt / rec.entry_value_usdt) if (rec.entry_value_usdt or 0) != 0 else 0.0,
            max_favorable_excursion_pct=pct(rec.max_favorable_excursion_pct),
            max_adverse_excursion_pct=pct(rec.max_adverse_excursion_pct),
            orders_submitted=int(rec.orders_submitted),
            orders_filled=int(rec.orders_filled),
            orders_canceled=int(rec.orders_canceled),
            spread_pct_at_entry=pct(rec.spread_pct_at_entry or 0.0),
            depth_L5_bid_usd=float(rec.depth_L5_bid_usd or 0.0),
            depth_L5_ask_usd=float(rec.depth_L5_ask_usd or 0.0),
            imbalance_L5=float(rec.imbalance_L5 or 0.0),
            tps_entry=float(rec.tps_entry or 0.0),
            volatility_1m_pct=float(rec.volatility_1m_pct or 0.0),
            volatility_5m_pct=float(rec.volatility_5m_pct or 0.0),
            funding_min_to_next=(float(rec.funding_min_to_next) if rec.funding_min_to_next is not None else None),
            trail_armed_at_price=(float(rec.trail_armed_at_price) if rec.trail_armed_at_price is not None else None),
            trail_steps=int(rec.trail_steps) if getattr(rec, "trail_steps", None) is not None else None,
            max_trail_offset_pct=(pct(rec.max_trail_offset_pct) if getattr(rec, "max_trail_offset_pct", None) is not None else None),
        )

    # 1) API key validation (skip on DRY_RUN or missing creds)
    if dry_run or not getattr(client, "api_key", "") or not getattr(client, "api_secret", ""):
        logger.info("DRY_RUN=true 또는 API 키 미설정: 지갑 인증 체크를 건너뜁니다.")
        wb = {"result": {"list": []}}
    else:
        try:
            account_type = os.environ.get("ACCOUNT_TYPE", "UNIFIED").upper()
            logger.info(
                f"Bybit base={client.base_url} category={category} accountType={account_type}"
            )
            wb = client.get_wallet_balance(accountType=account_type, coin="USDT")
            logger.info("Wallet balance call OK: retCode=0")
            slog.log_info(
                ts=int(time.time() * 1000),
                symbol=None,
                tag="wallet_balance",
                payload=wb.get("result", {}),
            )
        except BybitAPIError as e:
            # One-shot fallback for account type mismatch
            if getattr(e, "ret_code", 0) in (401, 403):
                alt = "CONTRACT" if account_type == "UNIFIED" else "UNIFIED"
                try:
                    logger.warning(
                        f"Wallet balance auth failed with {account_type}; retrying with {alt}"
                    )
                    wb = client.get_wallet_balance(accountType=alt, coin="USDT")
                    logger.info("Wallet balance call OK on fallback: retCode=0")
                    slog.log_info(
                        ts=int(time.time() * 1000),
                        symbol=None,
                        tag="wallet_balance",
                        payload=wb.get("result", {}),
                    )
                except BybitAPIError as e2:
                    logger.error(f"Wallet balance failed: {e2}")
                    logger.error(
                        "Auth failed (401/403). Check: TESTNET key pair, ACCOUNT_TYPE (UNIFIED vs CONTRACT), IP whitelist, and system time."
                    )
                    sys.exit(2)
            else:
                logger.error(f"Wallet balance failed: {e}")
                sys.exit(2)

    # Extract equity and free balance (best effort)
    equity = 0.0
    free = 0.0
    try:
        acct = wb.get("result", {}).get("list", [{}])[0]
        total_equity = float(acct.get("totalEquity") or 0)
        equity = total_equity
        # Free balance fallbacks across account types/edges
        free = equity
    except Exception:
        pass
    logger.info(f"Equity={equity:.2f} USDT, Free={free:.2f} USDT")

    # Try to load account-specific fee rates (maker/taker)
    try:
        fr = client.get_fee_rate(category=category, symbol=os.environ.get("BYBIT_SYMBOL", "BTCUSDT"))
        it = (fr.get("result", {}).get("list", []) or [{}])[0]
        mk = it.get("makerFeeRate")
        tk = it.get("takerFeeRate")
        if mk is not None:
            maker_fee_bps = max(0.0, float(mk) * 1e4)
        if tk is not None:
            taker_fee_bps = max(0.0, float(tk) * 1e4)
        logger.info(f"Fee rates (bps): maker={maker_fee_bps:.4f}, taker={taker_fee_bps:.4f}")
        slog.log_info(ts=int(time.time() * 1000), symbol=None, tag="fee_rates", payload={"maker_bps": maker_fee_bps, "taker_bps": taker_fee_bps})
    except BybitAPIError as e:
        logger.warning(f"Fee rate fetch failed; using defaults/env: {e}")
        # Fallback to env if provided
        maker_fee_bps = _env_float("MAKER_FEE_BPS", maker_fee_bps)
        taker_fee_bps = _env_float("TAKER_FEE_BPS", taker_fee_bps)

    # Build symbol universe (YAML)
    uni = build_universe(client, topN=runtime.params.universe.topN, discover=bool(getattr(runtime.app.runtime, 'discover_symbols', True)))
    # Exclude symbols with open positions from search/rotation
    try:
        pos_all = client.get_positions(category=category, settleCoin="USDT")
        plist = pos_all.get("result", {}).get("list", [])
        open_syms = {
            str(p.get("symbol"))
            for p in plist
            if p.get("symbol") and abs(float(p.get("size") or 0)) > 0
        }
    except Exception:
        open_syms = set()
    symbols = [s for s in uni.symbols if s not in open_syms]
    if not symbols:
        symbols = uni.symbols  # fallback: do not block rotation entirely
    logger.info(
        f"Universe: {len(symbols)} symbols ({'discovered' if uni.discovered else 'static'}) -> {symbols}"
    )
    if open_syms:
        logger.info(f"Excluded (open positions): {sorted(list(open_syms))}")
    # Rebind for rotation loop
    from bot.core.rotation import Universe as _U
    uni = _U(symbols=symbols, discovered=uni.discovered)
    slog.log_info(
        ts=int(time.time() * 1000),
        symbol=None,
        tag="universe",
        payload={"symbols": uni.symbols, "discovered": uni.discovered},
    )

    # Optional: start private WS for live event logging
    ws = None
    if enable_ws and BybitPrivateWS is not None:

        # Exit hint cache per symbol from execution/order topics
        exit_hint: dict[str, str] = {}
        last_summary_ms = int(time.time() * 1000)
        SUMMARY_INTERVAL_MS = int(getattr(runtime.app.runtime, 'summary_interval_sec', 600)) * 1000

        def _on_ws_msg(msg: dict[str, Any]) -> None:
            # Minimal parse for execution/order topics to enrich ledger
            try:
                topic = str(msg.get("topic") or "")
                data = msg.get("data") or msg.get("result") or {}
                now_ts = int(time.time() * 1000)
                if topic.startswith("execution"):
                    items = data if isinstance(data, list) else data.get("list") or []
                    for it in items:
                        try:
                            sym = it.get("symbol")
                            side = str(it.get("side") or "").upper()
                            px = float(it.get("execPrice") or 0)
                            q = float(it.get("execQty") or 0)
                            fee = float(it.get("execFee") or 0)
                            is_maker = bool(it.get("isMaker"))
                            link = it.get("orderLinkId")
                            otype = str(it.get("orderType") or "")
                            stop_type = str(it.get("stopOrderType") or "")
                            if otype.lower() == "takeprofit" or stop_type.lower() == "takeprofit":
                                if sym:
                                    exit_hint[sym] = "TP"
                            elif otype.lower() == "stoploss" or stop_type.lower() == "stoploss":
                                if sym:
                                    # trailing vs plain SL 구분은 추후 세분화
                                    exit_hint[sym] = "SL"
                            # mid ref unknown here; pass None
                            if sym:
                                try:
                                    ledger.on_execution(symbol=sym, side=side, price=px, qty=q, fee_usdt=fee, is_maker=is_maker, order_link_id=link, mid_ref=None)
                                except Exception:
                                    pass
                        except Exception:
                            continue
                elif topic.startswith("order"):
                    items = data if isinstance(data, list) else data.get("list") or []
                    for it in items:
                        try:
                            sym = it.get("symbol")
                            st = str(it.get("orderStatus") or "")
                            if st.lower() == "cancelled" and sym:
                                try:
                                    ledger.on_order_canceled(sym)
                                except Exception:
                                    pass
                            # Filled reduce-only order may imply manual/time-stop exit
                            ro = bool(it.get("reduceOnly") is True)
                            if st.lower() == "filled" and ro and sym:
                                # 수동/타임스탑에 의한 종료 힌트
                                exit_hint[sym] = exit_hint.get(sym, "MANUAL")
                        except Exception:
                            continue
                elif topic.startswith("position"):
                    items = data if isinstance(data, list) else data.get("list") or []
                    for it in items:
                        try:
                            sym = it.get("symbol")
                            sz = abs(float(it.get("size") or 0))
                            if sym and sz == 0 and sym in ledger.active:
                                # Finalize trade on position close
                                rec = ledger.active.get(sym)
                                if rec:
                                    # avg exit price from accumulated executions if available
                                    avg_exit = rec.exit_value_usdt / rec.exit_qty_filled if rec.exit_qty_filled > 0 else rec.exit_price or 0.0
                                    if avg_exit <= 0:
                                        avg_exit = float(it.get("avgPrice") or 0.0) or 0.0
                                    # realized PnL approx
                                    if rec.side == "LONG":
                                        realized = (avg_exit - rec.entry_price) * rec.entry_qty - (rec.entry_fee_usdt + rec.exit_fee_usdt)
                                    else:
                                        realized = (rec.entry_price - avg_exit) * rec.entry_qty - (rec.entry_fee_usdt + rec.exit_fee_usdt)
                                    reason = exit_hint.get(sym, rec.exit_reason or "MANUAL")
                                    rec_done = ledger.on_exit(
                                        symbol=sym,
                                        exit_ts=now_ts,
                                        price=avg_exit or rec.exit_price,
                                        qty=rec.entry_qty,
                                        reason=reason,
                                        exit_liquidity=rec.exit_liquidity,
                                        exit_fee_usdt=rec.exit_fee_usdt,
                                        exit_slippage_pct=rec.exit_slippage_pct,
                                        realized_pnl_usdt=realized,
                                        exit_mid_ref=None,
                                    )
                                    # Emit per-trade ledger row if enabled
                                    try:
                                        if tl_writer and rec_done and TradeLedgerRow is not None:
                                            row = _build_row_from_rec(run_id, rec_done)
                                            tl_writer.append(row, formats=tle_formats)
                                    except Exception:
                                        pass
                        except Exception:
                            continue
                # periodic summary flush
                try:
                    if now_ts - last_summary_ms >= SUMMARY_INTERVAL_MS:
                        ledger.write_daily_summary()
                        last_summary_ms = now_ts
                except Exception:
                    pass
                # Always keep raw log for debugging
                slog.log_info(ts=now_ts, symbol=None, tag="ws", payload=msg)
            except Exception:
                slog.log_info(ts=int(time.time() * 1000), symbol=None, tag="ws_err", payload={"raw": str(msg)[:200]})

        def _on_ws_err(err: Exception) -> None:
            logger.warning(f"WS error: {err}")

        try:
            ws = BybitPrivateWS(on_message=_on_ws_msg, on_error=_on_ws_err)
            ws.start()
            logger.info("Private WS started (order/execution/position)")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Private WS failed to start: {e}")

    # Rotation loop config
    loop_interval = float(getattr(runtime.app.runtime, 'no_trade_sleep_sec', 5.0))
    consensus_ticks = int(getattr(runtime.app.runtime, 'consensus_ticks', 3))
    loop_idle = float(getattr(runtime.app.runtime, 'loop_idle_sec', 1.0))
    fixed_notional = _env_float("ORDER_SIZE_USDT", 0.0)
    exit_flag = ExitFlag()
    idx = 0
    blacklist: dict[str, int] = {}

    while not exit_flag.check():
        try:
            if bool(getattr(runtime.app.runtime, 'refresh_universe_each_loop', True)):
                uni = LiveTestnetOrchestrator.refresh_universe(client, runtime, category, logger)
        except Exception:
            pass

        symbol = uni.symbols[idx % max(1, len(uni.symbols))]
        # Skip blacklisted symbols until expiry
        now_s = int(time.time())
        if symbol in blacklist and blacklist[symbol] > now_s:
            idx += 1
            continue
        idx += 1

        # 1.5) Load instrument filters & set leverage (via orchestrator)
        flt = LiveTestnetOrchestrator.load_instrument_filters(client, category, symbol, logger)
        LiveTestnetOrchestrator.set_leverage(client, symbol, leverage, category, logger)

        # Per-symbol tick loop
        mids: list[float] = []
        closes = Rolling(maxlen=120)
        vols = Rolling(maxlen=120)
        traded = False
        # Estimated entry info for fee-inclusive realized PnL on partial closes
        est_entry: dict[str, float | str] | None = None  # keys: side, qty, avg, fee_remain

        ob_depth = _env_int("ORDERBOOK_DEPTH", 1)
        ob_ctx = LiveTestnetOrchestrator.get_orderbook_context(
            client, symbol=symbol, category=category, ob_depth=ob_depth, logger=logger, slog=slog
        )
        mid = ob_ctx["mid"]
        spread = ob_ctx["spread"]
        bid_sz = ob_ctx["bid_sz"]
        ask_sz = ob_ctx["ask_sz"]
        obi = ob_ctx["obi"]
        parse_ok = bool(ob_ctx["parse_ok"]) 
        if not parse_ok:
            blacklist[symbol] = int(time.time()) + 300
            slog.log_why_no_trade(
                ts=int(time.time() * 1000),
                symbol=symbol,
                reasons=["parse_error:orderbook"],
                context={},
            )
            time.sleep(loop_interval)
            continue
        mids.append(mid)
        closes.add(mid)
        vols.add(max(0.0, bid_sz + ask_sz))
        if len(mids) > 50:
            mids.pop(0)
        logger.info(
            f"[{symbol} {i + 1}/{consensus_ticks}] mid={mid:.2f} spread={spread:.5f} obi={obi:.2f}"
        )

        # Regime pause checks (liquidity/spread) with strictness factor
        strict = str(getattr(runtime.params.regime, 'strictness', 'strict')).lower()
        factor = 1.0
        if strict == "off":
            factor = 10.0
        elif strict == "loose":
            factor = 3.0
        depth_ok = (bid_sz + ask_sz) * mid >= (min_depth_usd / factor)
        spread_ok = spread < (spread_threshold * spread_pause_mult * factor)
        if not (depth_ok and spread_ok):
            reasons = []
            if not depth_ok:
                reasons.append(f"depth<{min_depth_usd / factor:.0f}")
            if not spread_ok:
                reasons.append(
                    f"spread={spread:.5f}>thr={(spread_threshold * spread_pause_mult * factor):.5f}"
                )
            logger.info("Regime=PAUSE; " + ", ".join(reasons))
            slog.log_why_no_trade(
                ts=int(time.time() * 1000),
                symbol=symbol,
                reasons=["regime_pause"] + reasons,
                context={"mid": mid},
            )
            time.sleep(loop_interval)
            continue

        # 2.9) Optional: skip symbols with existing position or opening orders to avoid duplicate invests
        try:
            if os.environ.get("AVOID_DUPLICATE_SYMBOL", "true").strip().lower() == "true":
                pos_now = client.get_positions(category=category, symbol=symbol)
                plist_now = pos_now.get("result", {}).get("list", [])
                has_pos = False
                if plist_now:
                    try:
                        p0 = plist_now[0]
                        has_pos = abs(float(p0.get("size") or 0)) > 0
                    except Exception:
                        has_pos = False
                if has_pos:
                    logger.info("Skip: existing position for symbol (avoid duplicate)")
                    slog.log_why_no_trade(
                        ts=int(time.time() * 1000),
                        symbol=symbol,
                        reasons=["skip_existing_position"],
                        context={},
                    )
                    time.sleep(loop_interval)
                    continue
                # Also skip if there are open opening orders (best-effort)
                if LiveTestnetOrchestrator.should_skip_for_open_position_or_orders(
                    client,
                    category=category,
                    symbol=symbol,
                    logger=logger,
                    slog=slog,
                    loop_interval=loop_interval,
                ):
                    continue
        except Exception:
            pass

        # 3) Strategy selection
        if strategy == "obflow":
            signal, feat, sig = LiveTestnetOrchestrator.decide_obflow_signal(
                symbol=symbol, mid=mid, spread=spread, bid_sz=bid_sz, ask_sz=ask_sz, obi=obi, ob_cfg=ob_cfg, logger=logger, slog=slog
            )
            if signal is None:
                time.sleep(loop_interval)
                continue
        else:
            signal, pack_scores = LiveTestnetOrchestrator.decide_pack_signal(
                symbol=symbol,
                closes=closes.list(),
                vols=vols.list(),
                obi=obi,
                spread=spread,
                spread_threshold=spread_threshold,
                logger=logger,
                slog=slog,
            )
            if signal is None:
                time.sleep(loop_interval)
                continue

        # Optional guard: avoid flipping position immediately on opposite signal
        try:
            allow_flip = os.environ.get("ALLOW_FLIP", "false").strip().lower() == "true"
            pos_now = client.get_positions(category=category, symbol=symbol)
            plist_now = pos_now.get("result", {}).get("list", [])
            if plist_now:
                p0 = plist_now[0]
                cur_size = abs(float(p0.get("size") or 0))
                cur_long = p0.get("side") == "Buy"
                if cur_size > 0:
                    sig_long = signal > 0
                    if (sig_long != cur_long) and not allow_flip:
                        logger.info("Opposite signal while position open; skip (ALLOW_FLIP=false)")
                        slog.log_why_no_trade(
                            ts=int(time.time() * 1000),
                            symbol=symbol,
                            reasons=["avoid_flip"],
                            context={"cur_side": ("LONG" if cur_long else "SHORT"), "sig": ("LONG" if sig_long else "SHORT")},
                        )
                        time.sleep(loop_interval)
                        continue
        except Exception:
            pass

        # Dynamic routing: default maker(PostOnly) unless strong signal suggests taker
        prefer_limit = bool(runtime.app.exchange.maker_post_only)
        dyn_taker = bool(execp.dynamic_taker_on_strong) if execp else True
        if dyn_taker:
            met = []
            # Simple proxies
            tps_min = float(execp.tps_min) if execp else 8.0
            imb_min = float(execp.imb_l5_min) if execp else 0.25
            spr_max = float(execp.spread_max) if execp else 0.0006
            if vols.list() and len(vols.list()) >= 2:
                tps = max(0.0, (vols.list()[-1] - vols.list()[-2]))  # crude proxy
                if tps >= tps_min:
                    met.append("tps")
            if abs(obi) >= imb_min:
                met.append("imb")
            if spread <= spr_max:
                met.append("spr")
            if len(met) >= 2:
                prefer_limit = False
                logger.info(f"Routing=taker by strong-signal ({','.join(met)})")
        # Avoid taker near funding if configured and nextFundingTime is close
        try:
            avoid_min = float(getattr(fund, 'avoid_taker_within_min', 5))
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

        plan = LiveTestnetOrchestrator.build_order_plan_and_log(
            signal=signal,
            symbol=symbol,
            mid=mid,
            equity=equity,
            leverage=leverage,
            flt=flt,
            prefer_limit=prefer_limit,
            post_only=prefer_limit and _env_bool("MAKER_POST_ONLY", True),
            fixed_notional=fixed_notional,
            logger=logger,
            slog=slog,
        )

        # Risk checks
        ok, reason = check_balance_guard(
            RiskContext(equity_usdt=equity, free_usdt=free, symbol=symbol, last_mid=mid)
        )
        if not ok:
            logger.warning(f"Risk blocked (balance): {reason}")
            slog.log_risk(
                ts=int(time.time() * 1000),
                symbol=symbol,
                ok=False,
                reason=reason,
                context={"stage": "balance_guard"},
            )
            break
        # Compare cap against effective notional (margin usage), not gross exposure
        notional_gross = plan.qty * mid
        eff_notional = notional_gross / max(leverage, 1e-9)
        cap = float(getattr(runtime.app.risk, 'max_alloc_pct', 0.02)) * equity
        if eff_notional > cap:
            reason = f"Order notional {eff_notional:.2f} exceeds cap {cap:.2f} (max_alloc_pct)"
            logger.warning(f"Risk blocked (size): {reason} (gross={notional_gross:.2f}, lev={leverage})")
            slog.log_risk(
                ts=int(time.time() * 1000),
                symbol=symbol,
                ok=False,
                reason=f"{reason}; gross={notional_gross:.2f}; lev={leverage}",
                context={"stage": "order_size"},
            )
            time.sleep(loop_interval)
            continue
        if plan.order_type == "Limit" and plan.price is not None:
            ok, reason = slippage_guard(plan.price, mid)
            if not ok:
                logger.warning(f"Risk blocked (slippage): {reason}")
                slog.log_risk(
                    ts=int(time.time() * 1000),
                    symbol=symbol,
                    ok=False,
                    reason=reason,
                    context={"stage": "slippage_guard"},
                )
                time.sleep(loop_interval)
                continue

        if dry_run:
            logger.info("DRY_RUN=true; skipping actual order placement this iteration")
            time.sleep(loop_interval)
            continue

        # 4) Place order and then cancel for smoke
        try:
            tick = flt.get("tickSize") if isinstance(flt, dict) else None
            try:
                tick = float(tick) if tick is not None else None
            except Exception:
                tick = None
            tp_on_create, sl_on_create = LiveTestnetOrchestrator.compute_attach_tpsl_on_create(
                plan=plan,
                mid=mid,
                ee=ee,
                prefer_limit=prefer_limit,
                maker_post_only=bool(getattr(runtime.app.exchange, 'maker_post_only', True)),
                fee_assume_entry=fee_assume_entry,
                fee_assume_exit=fee_assume_exit,
                maker_fee_bps=maker_fee_bps,
                taker_fee_bps=taker_fee_bps,
                tick=tick,
            )
            res, est_entry = LiveTestnetOrchestrator.place_order_and_record(
                client=client,
                symbol=symbol,
                category=category,
                plan=plan,
                tp_on_create=tp_on_create,
                sl_on_create=sl_on_create,
                position_mode=_position_mode(),
                logger=logger,
                slog=slog,
                ledger=ledger,
                mid=mid,
                spread=spread,
                obi=obi,
                maker_fee_bps=maker_fee_bps,
                taker_fee_bps=taker_fee_bps,
            )
            traded = True

            # --- After entry: refresh position, reset trailing-stop, and re-apply based on actual avg_price ---
            try:
                # Small retry to allow position snapshot to reflect
                avg_price_actual = None
                side_long_actual = None
                for _ in range(3):
                    try:
                        pos_now = client.get_positions(category=category, symbol=symbol)
                        plist_now = pos_now.get("result", {}).get("list", [])
                        if plist_now:
                            p0 = plist_now[0]
                            sz = abs(float(p0.get("size") or 0))
                            if sz > 0:
                                avg_price_actual = float(p0.get("avgPrice") or 0)
                                side_long_actual = p0.get("side") == "Buy"
                                break
                    except Exception:
                        pass
                    time.sleep(0.2)

                if avg_price_actual and avg_price_actual > 0 and side_long_actual is not None:
                    # Cancel existing trailing stop first (if any)
                    try:
                        client.set_trading_stop(
                            symbol=symbol,
                            trailingStop="",
                            category=category,
                            positionIdx=(1 if side_long_actual else 2) if _position_mode() == "HEDGE" else None,
                        )
                        logger.info("Cleared existing trailing stop (if any)")
                    except BybitAPIError:
                        pass

                    # Compute fee-aware TP/SL at actual avg and round to favorable ticks
                    fe_bps = maker_fee_bps if os.environ.get("FEE_ASSUME_ENTRY", "auto").lower() == "maker" else (
                        taker_fee_bps if os.environ.get("FEE_ASSUME_ENTRY", "auto").lower() == "taker" else (maker_fee_bps if is_maker_entry else taker_fee_bps)
                    )
                    fx_bps = taker_fee_bps if os.environ.get("FEE_ASSUME_EXIT", "taker").lower() != "maker" else maker_fee_bps
                    tp_abs2, sl_abs2 = _fee_aware_targets(
                        avg_price_actual,
                        side_long=bool(side_long_actual),
                        tp_net=_env_float("TP_PCT", 0.0010),
                        sl_net=_env_float("SL_PCT", 0.0020),
                        entry_fee_bps=fe_bps,
                        exit_fee_bps=fx_bps,
                    )
                    tick = flt.get("tickSize") if isinstance(flt, dict) else None
                    try:
                        tick = float(tick) if tick is not None else None
                    except Exception:
                        tick = None
                    if tick and tick > 0:
                        if side_long_actual:
                            tp_abs2 = _round_to_tick(tp_abs2, tick, up=True)
                            sl_abs2 = _round_to_tick(sl_abs2, tick, up=False)
                        else:
                            tp_abs2 = _round_to_tick(tp_abs2, tick, up=False)
                            sl_abs2 = _round_to_tick(sl_abs2, tick, up=True)
                    trailing_abs2 = round(avg_price_actual * _env_float("SL_PCT", 0.0020), 4)

                    try:
                        client.set_trading_stop(
                            symbol=symbol,
                            trailingStop=trailing_abs2,
                            takeProfit=tp_abs2,
                            stopLoss=sl_abs2,
                            category=category,
                            positionIdx=(1 if side_long_actual else 2) if _position_mode() == "HEDGE" else None,
                        )
                        logger.info(
                            f"Applied trailing stop after entry: tp={tp_abs2:.6f} sl={sl_abs2:.6f} trail={trailing_abs2:.6f}"
                        )
                        try:
                            ledger.set_stops(symbol, tp_abs=tp_abs2, sl_abs=sl_abs2, trail_abs=trailing_abs2)
                        except Exception:
                            pass
                    except BybitAPIError as e:
                        logger.warning(f"Set trailing stop after entry failed: {e}")
            except Exception:
                pass
        except BybitAPIError as e:
            logger.error(f"Place order failed: {e}")
            time.sleep(loop_interval)
            continue

        # Reflect open orders and positions
        oo = LiveTestnetOrchestrator.log_open_orders(client, symbol=symbol, logger=logger, slog=slog)

        LiveTestnetOrchestrator.handle_positions_after_entry(
            client=client,
            category=category,
            symbol=symbol,
            strategy=strategy,
            mid=mid,
            spread=spread,
            obi=obi,
            prefer_limit=prefer_limit,
            flt=flt,
            maker_fee_bps=maker_fee_bps,
            taker_fee_bps=taker_fee_bps,
            ledger=ledger,
            tl_writer=tl_writer,
            tle_formats=tle_formats,
            row_builder=_build_row_from_rec,
            run_id=run_id,
            logger=logger,
            slog=slog,
            est_entry=est_entry,
        )

        # Try to cancel by orderLinkId for smoke (disable via SKIP_SMOKE_CANCEL=true)
        LiveTestnetOrchestrator.cancel_if_open(
            client=client,
            symbol=symbol,
            plan=plan,
            oo=oo,
            logger=logger,
            slog=slog,
        )

        time.sleep(loop_interval)

        if not traded:
            logger.info(
                f"No consensus for {symbol} after {consensus_ticks} ticks → rotating"
            )
            time.sleep(loop_idle)

    logger.info("Exit requested; stopping rotation loop")

    # Graceful WS shutdown if enabled
    try:
        if enable_ws and "ws" in locals() and ws is not None:
            ws.stop()
    except Exception:
        pass
    # Final summary flush
    try:
        ledger.write_daily_summary()
    except Exception:
        pass


if __name__ == "__main__":
    main()
