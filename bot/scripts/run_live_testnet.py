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
    require_env_flags(logger)
    # Load profile config if requested
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
    category = os.environ.get("BYBIT_CATEGORY", "linear")
    # Load YAML once for OB-Flow thresholds
    runtime = load_runtime()
    ob_cfg = OBFlowConfig.from_params(runtime.params)
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

    leverage = _env_float("LEVERAGE", _env_float("LEVERAGE_DEFAULT", 10.0))
    enable_ws = _env_bool("ENABLE_PRIVATE_WS", False)
    # Fee rates (bps); will try API first, then fallback to env/defaults
    maker_fee_bps = 2.0
    taker_fee_bps = 5.5
    fee_assume_entry = os.environ.get("FEE_ASSUME_ENTRY", "auto").lower()  # auto|maker|taker
    fee_assume_exit = os.environ.get("FEE_ASSUME_EXIT", "taker").lower()   # maker|taker
    # Regime/signal thresholds
    spread_threshold = _env_float("MIS_SPREAD_THRESHOLD", 0.0004)
    spread_pause_mult = _env_float("SPREAD_PAUSE_MULT", 3.0)
    min_depth_usd = _env_float("MIN_DEPTH_USD", 5000.0)

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

    # Build symbol universe
    uni = build_universe(client)
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
            slog.log_info(
                ts=int(time.time() * 1000), symbol=None, tag="ws", payload=msg
            )

        def _on_ws_err(err: Exception) -> None:
            logger.warning(f"WS error: {err}")

        try:
            ws = BybitPrivateWS(on_message=_on_ws_msg, on_error=_on_ws_err)
            ws.start()
            logger.info("Private WS started (order/execution/position)")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Private WS failed to start: {e}")

    # Rotation loop config
    loop_interval = _env_float(
        "NO_TRADE_SLEEP_SEC", _env_float("LOOP_INTERVAL_SEC", 5.0)
    )
    consensus_ticks = _env_int("CONSENSUS_TICKS", 3)
    loop_idle = _env_float("LOOP_IDLE_SEC", 1.0)
    fixed_notional = _env_float("ORDER_SIZE_USDT", 0.0)
    exit_flag = ExitFlag()
    idx = 0
    blacklist: dict[str, int] = {}

    while not exit_flag.check():
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
        strict = os.environ.get("REGIME_STRICTNESS", "strict").lower()
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

        prefer_limit = spread <= 0.0005 and _env_bool("PREFER_LIMIT_DEFAULT", True)
        # Avoid taker near funding if configured and nextFundingTime is close
        try:
            avoid_min = _env_float("AVOID_TAKER_WITHIN_MIN", 5.0)
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
        ok, reason = check_order_size(eff_notional, equity)
        if not ok:
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
                    po = prefer_limit and _env_bool("MAKER_POST_ONLY", True)
                    fe_bps = maker_fee_bps if ((plan.order_type == "Limit") and po) else taker_fee_bps
                fx_bps = taker_fee_bps if fee_assume_exit != "maker" else maker_fee_bps
                base_px = float(plan.price if plan.price is not None else mid)
                tp_on_create, sl_on_create = _fee_aware_targets(
                    base_px,
                    side_long=side_long,
                    tp_net=_env_float("TP_PCT", 0.0010),
                    sl_net=_env_float("SL_PCT", 0.0020),
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
                            slog.log_pnl(
                                ts=int(time.time() * 1000),
                                symbol=symbol,
                                realized=0.0,
                                unrealized=None,
                            )
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
