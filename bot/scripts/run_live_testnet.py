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
    from bot.utils.structlog import StructLogger, init_run_dir
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

import yaml  # type: ignore

try:
    from bot.core.exchange.bybit_ws import BybitPrivateWS  # type: ignore # noqa: E402
except Exception:  # noqa: BLE001
    BybitPrivateWS = None  # type: ignore


def setup_loggers(run_id: str) -> tuple[logging.Logger, _P]:
    base_logs = _P("logs")
    base_logs.mkdir(parents=True, exist_ok=True)
    # Run-scoped directory
    logs_dir = init_run_dir(base_logs, run_id)
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
    # Back-compat raw writer (kept if external callers rely on it)
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
    # if flags["LIVE_MODE"] != "true" or flags["TESTNET"] != "true":
    #     logger.error(
    #         "Safety check: run_live_testnet requires LIVE_MODE=true and TESTNET=true. Exiting."
    #     )
    #     sys.exit(1)


def _load_dotenv_if_present() -> int:
    """Lightweight .env loader to ease local runs (no external deps).

    Loads key=value pairs from repo-root `.env` if present. Does not override already-set env vars.
    Returns number of variables loaded.
    """
    try:
        env_fp = _P(__file__).resolve().parents[2] / ".env"
    except Exception:
        return 0
    if not env_fp.exists():
        return 0
    loaded = 0
    for line in env_fp.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        if "#" in v:
            v = v.split("#", 1)[0].strip()
        if k and (k not in os.environ):
            os.environ[k] = v
            loaded += 1
    return loaded


def _apply_profile_env(profile: str) -> None:
    # Load overlay YAML and map key settings to envs the runner uses.
    # Priority: CLI overrides > profile overlay > base env
    prof_path = _P(
        f"bot/configs/profiles/{'quick_test' if profile == 'quick-test' else profile}.yaml"
    )
    if not prof_path.exists():
        return
    with prof_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Exchange/network
    net = (cfg.get("exchange", {}) or {}).get("network")
    if net:
        os.environ.setdefault(
            "TESTNET", "true" if str(net).lower() == "testnet" else "false"
        )
    maker_post = (cfg.get("exchange", {}) or {}).get("maker_post_only")
    if maker_post is not None:
        os.environ.setdefault("MAKER_POST_ONLY", str(bool(maker_post)).lower())
    taker_on = (cfg.get("exchange", {}) or {}).get("taker_on_strong_score")
    if taker_on is not None:
        os.environ.setdefault("TAKER_ON_STRONG_SCORE", str(bool(taker_on)).lower())
    fallback_ioc = (cfg.get("exchange", {}) or {}).get("fallback_ioc")
    if fallback_ioc is not None:
        os.environ.setdefault("FALLBACK_IOC", str(bool(fallback_ioc)).lower())

    # Params overlays
    params = cfg.get("params", {}) or {}
    orderbook = params.get("orderbook", {}) or {}
    if "min_depth_usd" in orderbook:
        os.environ.setdefault("MIN_DEPTH_USD", str(orderbook["min_depth_usd"]))
    regime = params.get("regime", {}) or {}
    if "strictness" in regime:
        os.environ.setdefault("REGIME_STRICTNESS", str(regime["strictness"]))

    # indicators/universe overlays reserved for strategy layer; ignored here
    # Quick-test: disable discovery by default
    if profile == "quick-test":
        os.environ.setdefault("DISCOVER_SYMBOLS", "false")

    # Entry/exit
    ex = cfg.get("entry_exit", {}) or {}
    if "tp1" in ex:
        os.environ.setdefault("TP_PCT", str(ex["tp1"]))
    # For SL, prefer existing SL_PCT env if set
    if "sl" in ex:
        os.environ.setdefault("SL_PCT", str(ex["sl"]))
    if "trail_after_tp1" in ex:
        os.environ.setdefault("TRAIL_AFTER_TP1_PCT", str(ex["trail_after_tp1"]))

    # Runtime
    rt = cfg.get("runtime", {}) or {}
    if "consensus_ticks" in rt:
        os.environ.setdefault("CONSENSUS_TICKS", str(rt["consensus_ticks"]))
    if "symbol_universe" in rt:
        os.environ.setdefault("SYMBOL_UNIVERSE", ",".join(rt["symbol_universe"]))
        os.environ.setdefault("DISCOVER_SYMBOLS", "false")
    if "poll_ms" in rt:
        os.environ.setdefault("POLL_MS", str(rt["poll_ms"]))

    # Risk overlays
    rk = cfg.get("risk", {}) or {}
    if "max_alloc_pct" in rk:
        os.environ.setdefault("MAX_ALLOC_PCT", str(rk["max_alloc_pct"]))
    if "min_free_balance_usdt" in rk:
        os.environ.setdefault("MIN_FREE_BALANCE_USDT", str(rk["min_free_balance_usdt"]))
    if "slippage_guard_pct" in rk:
        os.environ.setdefault("SLIPPAGE_GUARD_PCT", str(rk["slippage_guard_pct"]))


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
        default=os.environ.get("STRATEGY", "pack"),
        choices=["pack", "obflow"],
        help="pack=기존 MIS/VRS/LSR, obflow=OB-Flow 신호 사용",
    )
    args = parser.parse_args()

    # Run ID and loggers
    run_id = f"run_{_dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    logger, logs_dir = setup_loggers(run_id)
    # Load .env if present (no override)
    n_loaded = _load_dotenv_if_present()
    if n_loaded:
        logger.info(f"Loaded {n_loaded} vars from .env")
    slog = StructLogger(logs_dir, run_id)
    ledger = TradeLedger(run_id=run_id, out_dir=Path("reports"))
    require_env_flags(logger)
    # Load YAML (single source) and export key params into ENV with precedence: YAML > ENV > Defaults
    runtime = load_runtime()
    def _export_resolved_from_yaml() -> None:
        resolved: dict[str, str | float | int | bool] = {}
        warnings: list[dict] = []
        # Map selected keys
        try:
            ee = runtime.params.entry_exit
            ob = runtime.params.orderbook
            fu = runtime.params.funding_time
            ex = runtime.app.exchange
            uv = runtime.params.universe
            mapping: list[tuple[str, object]] = [
                ("TP_PCT", ee.tp1),
                ("SL_PCT", ee.sl),
                ("TRAIL_AFTER_TP1_PCT", ee.trail_after_tp1),
                ("MIN_DEPTH_USD", ob.min_depth_usd),
                ("AVOID_TAKER_WITHIN_MIN", fu.avoid_taker_within_min),
                ("PREFER_LIMIT_DEFAULT", bool(ex.maker_post_only)),
                ("DYNAMIC_TAKER_ON_STRONG", bool(ex.taker_on_strong_score)),
                ("FALLBACK_IOC", bool(ex.fallback_ioc)),
                ("UNIVERSE_TOP_N", uv.topN),
                ("BYBIT_CATEGORY", ex.category),
            ]
            for key, yval in mapping:
                ystr = str(yval).lower() if isinstance(yval, bool) else str(yval)
                prev = os.environ.get(key)
                if prev is not None and prev != ystr:
                    warnings.append({"key": key, "env": prev, "yaml": ystr})
                os.environ[key] = ystr
                resolved[key] = yval
        except Exception as e:  # noqa: BLE001
            logger.warning(f"config:resolved export failed: {e}")
        if warnings:
            logger.warning(f"config:resolved conflicts: {warnings}")
            try:
                from bot.utils.structlog import BaseEvent
                # emit conflict event
                for w in warnings:
                    slog.log_info(ts=int(time.time()*1000), symbol=None, tag="config:conflict", payload=w)  # type: ignore[arg-type]
            except Exception:
                pass
        # Dump resolved
        try:
            slog.log_info(ts=int(time.time() * 1000), symbol=None, tag="config:resolved", payload=resolved)  # type: ignore[arg-type]
        except Exception:
            logger.info(f"config:resolved {resolved}")

    _export_resolved_from_yaml()
    # Load profile config if requested (overrides after base YAML export)
    if args.profile:
        try:
            if args.profile == "quick-test":
                qpath = _P("bot/configs/quick_test.yaml")
                if qpath.exists():
                    with qpath.open("r", encoding="utf-8") as f:
                        _ = yaml.safe_load(f)  # reserved for future deep merge
                _apply_profile_env("quick-test")
                logger.info("Applied quick-test profile overrides")
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
    strategy = (args.strategy or "").strip().lower()
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

    # 1) API key validation
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
                        except Exception:
                            continue
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
        # Optionally refresh universe each loop to keep symbols up-to-date
        try:
            if bool(getattr(runtime.app.runtime, 'refresh_universe_each_loop', True)):
                uni_new = build_universe(client, topN=runtime.params.universe.topN, discover=bool(getattr(runtime.app.runtime, 'discover_symbols', True)))
                # Exclude symbols with open positions best-effort
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
                symbols_ref = [s for s in uni_new.symbols if s not in open_syms] or uni_new.symbols
                if symbols_ref:
                    from bot.core.rotation import Universe as _U
                    uni = _U(symbols=symbols_ref, discovered=uni_new.discovered)
        except Exception:
            pass

        symbol = uni.symbols[idx % max(1, len(uni.symbols))]
        # Skip blacklisted symbols until expiry
        now_s = int(time.time())
        if symbol in blacklist and blacklist[symbol] > now_s:
            idx += 1
            continue
        idx += 1

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
            client.set_leverage(
                symbol=symbol,
                buyLeverage=int(leverage),
                sellLeverage=int(leverage),
                category=category,
            )
            logger.info("Leverage set OK")
        except BybitAPIError as e:
            if getattr(e, "ret_code", None) == 110043:
                logger.info("Leverage unchanged (110043): desired leverage already set")
            else:
                logger.warning(f"Set leverage failed: {e}")

        # Per-symbol tick loop
        mids: list[float] = []
        closes = Rolling(maxlen=120)
        vols = Rolling(maxlen=120)
        traded = False
        # Estimated entry info for fee-inclusive realized PnL on partial closes
        est_entry: dict[str, float | str] | None = None  # keys: side, qty, avg, fee_remain

        ob_depth = _env_int("ORDERBOOK_DEPTH", 1)
        for i in range(consensus_ticks):
            if exit_flag.check():
                break
            ob = client.get_orderbook(symbol=symbol, depth=ob_depth, category=category)
        slog.log_info(
            ts=int(time.time() * 1000),
            symbol=symbol,
            tag="orderbook",
            payload=ob.get("result", {}),
        )
        parse_ok = False
        try:
            bids = ob["result"]["b"] if ob.get("result") and ob["result"].get("b") else []
            asks = ob["result"]["a"] if ob.get("result") and ob["result"].get("a") else []
            if not bids or not asks:
                raise ValueError("empty bids/asks")
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            bid_sz = float(bids[0][1]) if len(bids[0]) > 1 else 0.0
            ask_sz = float(asks[0][1]) if len(asks[0]) > 1 else 0.0
            mid = (best_bid + best_ask) / 2
            spread = (best_ask - best_bid) / mid if mid > 0 else 0.0
            obi = (
                (bid_sz - ask_sz) / (bid_sz + ask_sz) if (bid_sz + ask_sz) > 0 else 0.0
            )
            parse_ok = True
        except Exception as e:
            logger.info(f"Failed to parse orderbook (fallback to ticker): {e}")
            # Fallback: use ticker for mid/spread estimate
            try:
                tk = client.get_tickers(category=category, symbol=symbol)
                it = (tk.get("result", {}).get("list", []) or [{}])[0]
                a1 = float(it.get("ask1Price") or 0)
                b1 = float(it.get("bid1Price") or 0)
                if a1 > 0 and b1 > 0:
                    mid = (a1 + b1) / 2
                    spread = (a1 - b1) / mid if mid > 0 else 0.0
                    bid_sz = float(it.get("bid1Size") or 0)
                    ask_sz = float(it.get("ask1Size") or 0)
                    obi = 0.0
                    logger.info("Used ticker-based mid/spread fallback")
                    parse_ok = True
            except Exception as e2:
                logger.warning(f"Ticker fallback failed: {e2}")
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
                try:
                    oo = client.get_open_orders(symbol=symbol)
                    raw_list = oo.get("result", {}).get("list", []) or []
                    # Consider only truly opening orders:
                    # - reduceOnly != True (we allow reduce-only orders to coexist)
                    # - orderStatus in open states (New/PartiallyFilled/Untriggered)
                    open_states = {"New", "PartiallyFilled", "Untriggered"}
                    olist = []
                    for it in raw_list:
                        try:
                            ro = it.get("reduceOnly") is True
                            st = str(it.get("orderStatus") or "").strip()
                            if ro:
                                continue
                            if st and st not in open_states:
                                continue
                            olist.append(it)
                        except Exception:
                            continue
                    if os.environ.get("DEBUG_OPEN_ORDERS", "false").lower() == "true":
                        logger.info(f"OpenOrders(raw={len(raw_list)} filtered={len(olist)}): sample={olist[0] if olist else None}")
                    if olist:
                        logger.info("Skip: open orders present for symbol (avoid duplicate)")
                        slog.log_why_no_trade(
                            ts=int(time.time() * 1000),
                            symbol=symbol,
                            reasons=["skip_open_orders"],
                            context={"open_orders": len(olist)},
                        )
                        time.sleep(loop_interval)
                        continue
                except Exception:
                    pass
        except Exception:
            pass

        # 3) Strategy selection
        if strategy == "obflow":
            # OB-Flow는 L2Book 특징이 필요 — mid/spread/마이크로를 기반으로 하므로 여기서 간단히 재계산
            from bot.core.book import L2Book
            from bot.core.features import basic_snapshot
            b = L2Book(symbol=symbol)
            # L1만 알고 있으므로 현재 bid/ask를 한 레벨로 반영
            b.bids[mid - spread / 2] = bid_sz or 1.0  # type: ignore[index]
            b.asks[mid + spread / 2] = ask_sz or 1.0  # type: ignore[index]
            feat = basic_snapshot(b)
            sig = obflow_decide(b, ob_cfg)
            if sig is None:
                logger.info("OB-Flow: no signal; sleeping")
                slog.log_signal(
                    ts=int(time.time() * 1000), symbol=symbol, scores={"obflow": feat}, decision=None
                )
                time.sleep(loop_interval)
                continue
            signal = +1 if str(sig["side"]).upper() == "BUY" else -1
            # Invert signals if requested: BUY->short, SELL->long
            try:
                if os.environ.get("INVERT_SIGNALS", "false").strip().lower() == "true":
                    signal *= -1
                    logger.info("Signal inversion active: flipping OB-Flow direction")
            except Exception:
                pass
            logger.info(f"OB-Flow selected: {sig['type']} -> {sig['side']}")
            slog.log_signal(
                ts=int(time.time() * 1000), symbol=symbol, scores={"obflow": feat}, decision=f"OBF:{sig['type']}:{sig['side']}"
            )
        else:
            sp = StrategyParams()
            mis = mis_signal(
                closes.list(),
                orderbook_imbalance=(obi + 1) / 2,
                spread=spread,
                spread_threshold=spread_threshold,
                params=sp,
            )
            vrs = vrs_signal(closes.list(), vols.list(), sp)
            wick_long = False
            trade_burst = (
                (bid_sz + ask_sz) > 0
                and vols.list()
                and (bid_sz + ask_sz) > 2.0 * max(1e-9, vols.list()[-1])
            )
            oi_drop = False
            lsr = lsr_signal(wick_long=wick_long, trade_burst=trade_burst, oi_drop=oi_drop)
            strat_name, strat_side = select_strategy(mis, vrs, lsr)
            if strat_name is None or strat_side is None:
                logger.info("No strategy consensus; sleeping")
                slog.log_signal(
                    ts=int(time.time() * 1000),
                    symbol=symbol,
                    scores={"mis": mis, "vrs": vrs, "lsr": lsr},
                    decision=None,
                )
                slog.log_why_no_trade(
                    ts=int(time.time() * 1000),
                    symbol=symbol,
                    reasons=["no_consensus"],
                    context={"mis": mis, "vrs": vrs, "lsr": lsr},
                )
                time.sleep(loop_interval)
                continue
            signal = +1 if str(strat_side) == "Side.BUY" or strat_side == "BUY" else -1
            try:
                if os.environ.get("INVERT_SIGNALS", "false").strip().lower() == "true":
                    signal *= -1
                    logger.info("Signal inversion active: flipping pack strategy direction")
            except Exception:
                pass
            logger.info(
                f"Strategy selected on {symbol}: {strat_name} -> {('BUY' if signal > 0 else 'SELL')}"
            )
            slog.log_signal(
                ts=int(time.time() * 1000),
                symbol=symbol,
                scores={"mis": mis, "vrs": vrs, "lsr": lsr},
                decision=f"{strat_name}:{'BUY' if signal > 0 else 'SELL'}",
            )

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
            post_only=prefer_limit and _env_bool("MAKER_POST_ONLY", True),
            fixed_notional_usdt=(fixed_notional if fixed_notional > 0 else None),
        )
        logger.info(
            f"OrderPlan: side={plan.side} qty={plan.qty:.6f} type={plan.order_type} tif={plan.tif} tp={plan.tp:.2f} sl={plan.sl:.2f}"
        )
        slog.log_order(
            ts=int(time.time() * 1000),
            symbol=symbol,
            plan={
                "side": plan.side,
                "qty": plan.qty,
                "order_type": plan.order_type,
                "tif": plan.tif,
                "price": plan.price,
                "tp": plan.tp,
                "sl": plan.sl,
            },
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
            # In one-way mode, TP/SL attached on create apply at position level.
            # Opposite-side orders may conflict (e.g., existing Buy position).
            # Default: do NOT attach TP/SL on create; apply via trading-stop later.
            attach = _env_bool("ATTACH_TPSL_ON_CREATE", False)
            # Fee-aware TP/SL on create if requested
            tp_on_create = None
            sl_on_create = None
            if attach and plan.tp is not None and plan.sl is not None:
                side_long = (plan.side.upper() == "BUY")
                if fee_assume_entry == "maker":
                    fe_bps = maker_fee_bps
                elif fee_assume_entry == "taker":
                    fe_bps = taker_fee_bps
                else:
                    po = prefer_limit and bool(getattr(runtime.app.exchange, 'maker_post_only', True))
                    fe_bps = maker_fee_bps if ((plan.order_type == "Limit") and po) else taker_fee_bps
                fx_bps = taker_fee_bps if fee_assume_exit != "maker" else maker_fee_bps
                base_px = float(plan.price if plan.price is not None else mid)
                tp_on_create, sl_on_create = _fee_aware_targets(
                    base_px,
                    side_long=side_long,
                    tp_net=float(ee.tp1),
                    sl_net=float(getattr(ee, 'sl', 0.0020)),
                    entry_fee_bps=fe_bps,
                    exit_fee_bps=fx_bps,
                )
                # Favorable tick rounding
                tick = flt.get("tickSize") if isinstance(flt, dict) else None
                try:
                    tick = float(tick) if tick is not None else None
                except Exception:
                    tick = None
                if tick and tick > 0:
                    if side_long:
                        tp_on_create = _round_to_tick(tp_on_create, tick, up=True)
                        sl_on_create = _round_to_tick(sl_on_create, tick, up=False)
                    else:
                        tp_on_create = _round_to_tick(tp_on_create, tick, up=False)
                        sl_on_create = _round_to_tick(sl_on_create, tick, up=True)
            pos_mode = _position_mode()
            pos_idx = _position_idx_for_side(plan.side, pos_mode)
            res = client.place_order(
                symbol=plan.symbol,
                side=plan.side,
                qty=str(round(plan.qty, 6)),
                orderType=plan.order_type,
                timeInForce=plan.tif,
                price=str(plan.price) if plan.price is not None else None,
                orderLinkId=plan.order_link_id,
                takeProfit=(str(tp_on_create) if attach and tp_on_create else None),
                stopLoss=(str(sl_on_create) if attach and sl_on_create else None),
                positionIdx=pos_idx,
            )
            slog.log_order(
                ts=int(time.time() * 1000),
                symbol=symbol,
                plan={
                    "side": plan.side,
                    "qty": plan.qty,
                    "order_type": plan.order_type,
                    "tif": plan.tif,
                    "price": plan.price,
                    "tp": plan.tp,
                    "sl": plan.sl,
                    "order_link_id": plan.order_link_id,
                },
                result=res,
            )
            logger.info("Order placed")
            traded = True
            # Trade ledger: entry record (best-effort)
            ledger.on_entry(
                symbol=symbol,
                side_long=(plan.side.upper() == "BUY"),
                entry_ts=int(time.time() * 1000),
                price=entry_px,
                qty=float(plan.qty),
                spread_pct=spread,
                imbalance_L5=obi,
                entry_liquidity=("maker" if (plan.order_type == "Limit" and po) else "taker"),
                entry_fee_usdt=entry_fee,
                entry_slippage_pct=0.0,
                entry_mid_ref=mid,
            )
            try:
                ledger.on_order_submitted(symbol, plan.order_link_id, for_entry=True)
            except Exception:
                pass
            # Estimate entry fee for later PnL calculations
            po = prefer_limit and _env_bool("MAKER_POST_ONLY", True)
            is_maker_entry = (plan.order_type == "Limit") and po
            entry_px = float(plan.price if plan.price is not None else mid)
            entry_notional = plan.qty * entry_px
            entry_fee = _fee_amount(entry_notional, maker_fee_bps if is_maker_entry else taker_fee_bps)
            est_entry = {"side": plan.side, "qty": float(plan.qty), "avg": entry_px, "fee_remain": entry_fee}

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
        try:
            oo = client.get_open_orders(symbol=symbol)
            slog.log_info(
                ts=int(time.time() * 1000), symbol=symbol, tag="open_orders", payload=oo
            )
        except BybitAPIError as e:
            logger.warning(f"Open orders fetch failed: {e}")

        try:
            pos = client.get_positions(category=category, symbol=symbol)
            slog.log_info(
                ts=int(time.time() * 1000), symbol=symbol, tag="positions", payload=pos
            )
            # Time stop and trailing if position present
            plist = pos.get("result", {}).get("list", [])
            if plist:
                p = plist[0]
                size = abs(float(p.get("size") or 0))
                side_long = p.get("side") == "Buy"
                avg_price = float(p.get("avgPrice") or 0)
                # OB-Flow partial TP logic
                if strategy == "obflow" and size > 0 and avg_price > 0:
                    try:
                        tp1 = _env_float("TP_PCT", 0.0012)
                        partial_pct = _env_float("PARTIAL_CLOSE_PCT", 0.5)
                        move = (
                            (mid - avg_price) / avg_price
                            if side_long
                            else (avg_price - mid) / avg_price
                        )
                        # Place reduce-only partial market close when TP1 reached
                        if move >= tp1 and partial_pct > 0:
                            pq = max(0.0, size * min(1.0, partial_pct))
                            if pq > 0:
                                try:
                                    pos_idx2 = 1 if side_long else 2 if _position_mode() == "HEDGE" else None
                                    client.place_order(
                                        symbol=symbol,
                                        side=("Sell" if side_long else "Buy"),
                                        qty=str(pq),
                                        orderType="Market",
                                        timeInForce="IOC",
                                        reduceOnly=True,
                                        category=category,
                                        positionIdx=pos_idx2,
                                    )
                                    logger.info(
                                        f"OB-Flow partial close executed qty={pq:.6f} at TP1 move={move:.5f}"
                                    )
                                    # Fee-inclusive realized PnL estimation (approx)
                                    gross = ((mid - avg_price) * pq) if side_long else ((avg_price - mid) * pq)
                                    close_fee = _fee_amount(pq * mid, taker_fee_bps)
                                    proportional_entry_fee = 0.0
                                    if est_entry is not None and float(est_entry.get("qty", 0.0)) > 0:
                                        base_qty = float(est_entry.get("qty", 0.0))
                                        fee_rem = float(est_entry.get("fee_remain", 0.0))
                                        if base_qty > 0:
                                            frac = min(1.0, pq / base_qty)
                                            proportional_entry_fee = fee_rem * frac
                                            est_entry["fee_remain"] = max(0.0, fee_rem - proportional_entry_fee)
                                            est_entry["qty"] = max(0.0, base_qty - pq)
                                    realized_net = gross - (proportional_entry_fee + close_fee)
                                    slog.log_pnl(ts=int(time.time() * 1000), symbol=symbol, realized=realized_net, unrealized=None)
                                except BybitAPIError as e:
                                    logger.warning(f"Partial close failed: {e}")
                    except Exception:
                        pass
                # Update MFE/MAE tracking while position open
                try:
                    ledger.update_mfe_mae(symbol, now_price=mid)
                except Exception:
                    pass
                # Simple trailing: if price moved favorably by trail_after_tp1, set trailingStop
                trail_after = _env_float("TRAIL_AFTER_TP1_PCT", 0.0008)
                tp_pct = _env_float("TP_PCT", 0.0010)
                sl_pct = _env_float("SL_PCT", 0.0020)
                if size > 0 and avg_price > 0:
                    move = (
                        (mid - avg_price) / avg_price
                        if side_long
                        else (avg_price - mid) / avg_price
                    )
                    if move >= trail_after:
                        try:
                            trailing_abs = round(avg_price * sl_pct, 4)
                            # Fee-aware TP/SL (net targets) mapped to absolute prices
                            fe_bps = maker_fee_bps if os.environ.get("FEE_ASSUME_ENTRY", "auto").lower() == "maker" else (
                                taker_fee_bps if os.environ.get("FEE_ASSUME_ENTRY", "auto").lower() == "taker" else taker_fee_bps
                            )
                            fx_bps = taker_fee_bps if os.environ.get("FEE_ASSUME_EXIT", "taker").lower() != "maker" else maker_fee_bps
                            tp_abs, sl_abs = _fee_aware_targets(
                                avg_price,
                                side_long=side_long,
                                tp_net=tp_pct,
                                sl_net=sl_pct,
                                entry_fee_bps=fe_bps,
                                exit_fee_bps=fx_bps,
                            )
                            # Favorable tick rounding
                            tick = flt.get("tickSize") if isinstance(flt, dict) else None
                            try:
                                tick = float(tick) if tick is not None else None
                            except Exception:
                                tick = None
                            if tick and tick > 0:
                                if side_long:
                                    tp_abs = _round_to_tick(tp_abs, tick, up=True)
                                    sl_abs = _round_to_tick(sl_abs, tick, up=False)
                                else:
                                    tp_abs = _round_to_tick(tp_abs, tick, up=False)
                                    sl_abs = _round_to_tick(sl_abs, tick, up=True)
                            client.set_trading_stop(
                                symbol=symbol,
                                trailingStop=trailing_abs,
                                takeProfit=tp_abs,
                                stopLoss=sl_abs,
                                category=category,
                                positionIdx=(1 if side_long else 2) if _position_mode() == "HEDGE" else None,
                            )
                            logger.info("Applied trailing stop via trading-stop API")
                        except BybitAPIError as e:
                            logger.warning(f"Trailing stop set failed: {e}")
                # Time stop: close if holding longer than threshold
                time_stop_sec = _env_int("TIME_STOP_SEC", 1200)
                et = p.get("updatedTime") or p.get("createdTime")  # ms
                if size > 0 and et is not None:
                    held_sec = max(0, int((int(time.time() * 1000) - int(et)) / 1000))
                    if held_sec >= time_stop_sec:
                        try:
                            qty = size
                            side = "SELL" if side_long else "BUY"
                            client.close_position_market(
                                symbol=symbol,
                                side=side,
                                qty=str(qty),
                                category=category,
                                positionIdx=(1 if side_long else 2) if _position_mode() == "HEDGE" else None,
                            )
                            logger.info(
                                f"Time stop triggered after {held_sec}s; closing position"
                            )
                            try:
                                # Attempt to fetch recent executions to compute realized PnL and fees
                                end_ms = int(time.time() * 1000)
                                start_ms = end_ms - 15 * 60 * 1000
                                ex = client.get_executions(symbol=symbol, category=category, start=start_ms, end=end_ms, limit=200)
                                fills = (ex.get("result", {}) or {}).get("list", [])
                                entry_fee = 0.0
                                exit_fee = 0.0
                                realized = 0.0
                                entry_px_agg = []
                                exit_px_agg = []
                                # Best-effort aggregation by side
                                for it in fills:
                                    try:
                                        qty_f = float(it.get("execQty") or 0)
                                        price_f = float(it.get("execPrice") or 0)
                                        fee_f = float(it.get("execFee") or 0)
                                        is_maker = bool(it.get("isMaker"))
                                        side_f = str(it.get("side") or "").upper()
                                        if side_f in {"BUY", "SELL"}:
                                            # Approx: use sign to compute PnL delta if both legs present
                                            realized += (price_f - avg_price) * qty_f if side_long and side_f == "SELL" else 0.0
                                            realized += (avg_price - price_f) * qty_f if (not side_long) and side_f == "BUY" else 0.0
                                            if (side_long and side_f == "BUY") or ((not side_long) and side_f == "SELL"):
                                                entry_px_agg.append((price_f, qty_f, is_maker))
                                            else:
                                                exit_px_agg.append((price_f, qty_f, is_maker))
                                        # Split fees roughly
                                        if side_f == ("BUY" if side_long else "SELL"):
                                            entry_fee += fee_f
                                        else:
                                            exit_fee += fee_f
                                    except Exception:
                                        continue
                                total_fee = entry_fee + exit_fee
                                # Determine exit reason heuristically
                                reason = "TIME_STOP"
                                try:
                                    rec = ledger.active.get(symbol)
                                    if rec and rec.tp_abs and rec.sl_abs:
                                        tol = (flt.get("tickSize") or 0.0) or 0.0
                                        last_exit_px = exit_px_agg[-1][0] if exit_px_agg else mid
                                        if side_long and abs(last_exit_px - rec.tp_abs) <= max(2*tol, rec.tp_abs*1e-5):
                                            reason = "TP"
                                        elif side_long and abs(last_exit_px - rec.sl_abs) <= max(2*tol, rec.sl_abs*1e-5):
                                            reason = "SL"
                                        elif (not side_long) and abs(last_exit_px - rec.tp_abs) <= max(2*tol, rec.tp_abs*1e-5):
                                            reason = "TP"
                                        elif (not side_long) and abs(last_exit_px - rec.sl_abs) <= max(2*tol, rec.sl_abs*1e-5):
                                            reason = "SL"
                                        else:
                                            reason = "TRAIL"
                                except Exception:
                                    pass
                                ledger.on_exit(
                                    symbol=symbol,
                                    exit_ts=end_ms,
                                    price=mid,
                                    qty=size,
                                    reason=reason,
                                    exit_liquidity="taker",
                                    exit_fee_usdt=exit_fee,
                                    exit_slippage_pct=0.0,
                                    realized_pnl_usdt=realized - total_fee,
                                    exit_mid_ref=mid,
                                )
                                try:
                                    ledger.write_daily_summary()
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        except BybitAPIError as e:
                            logger.warning(f"Time stop close failed: {e}")
        except BybitAPIError as e:
            logger.warning(f"Positions fetch failed: {e}")

        # Try to cancel by orderLinkId for smoke (disable via SKIP_SMOKE_CANCEL=true)
        if os.environ.get("SKIP_SMOKE_CANCEL", "false").lower() != "true":
            # Only attempt cancel for resting limits; market/IOC usually gone immediately
            should_cancel = (plan.order_type == "Limit")
            if should_cancel:
                # Cancel only if still open (best-effort check)
                is_open = True
                try:
                    lst = oo.get("result", {}).get("list", []) if "oo" in locals() else []  # type: ignore[name-defined]
                    if lst:
                        open_ids = {it.get("orderLinkId") for it in lst}
                        is_open = plan.order_link_id in open_ids
                except Exception:
                    pass
                if not is_open:
                    logger.info("Skip cancel: order not open (filled/rejected/already canceled)")
                else:
                    try:
                        cres = client.cancel_order(symbol=symbol, orderLinkId=plan.order_link_id)
                        slog.log_cancel(
                            ts=int(time.time() * 1000),
                            symbol=symbol,
                            order_link_id=plan.order_link_id,
                            reason="rotate_or_smoke",
                        )
                        logger.info("Order cancel sent")
                    except BybitAPIError as e:
                        # 110001: order not exists or too late to cancel — benign in smoke flows
                        if getattr(e, "ret_code", None) == 110001:
                            logger.info("Cancel skipped: order already not open (110001)")
                        else:
                            logger.error(f"Cancel failed: {e}")

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


if __name__ == "__main__":
    main()
