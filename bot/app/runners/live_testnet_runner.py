"""Helpers and facade for live testnet runner.

This module exposes small utilities used by `bot/scripts/run_live_testnet.py`
to keep that script slim while preserving its behavior.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path as _P
from typing import Any
import time

from bot.utils.structlog import init_run_dir
from bot.app.runners.live_runner import LiveRunner


class LiveTestnetOrchestrator:
    """Orchestrates non-network side-effects for the live testnet runner.

    Provides small, testable helpers to keep the script slim without changing
    the behavior or external outputs.
    """

    @staticmethod
    def apply_strategy_overrides(app_cfg: Any, cli_name: str | None, cli_params: list[str] | None) -> None:
        name = (cli_name or "").strip()
        if name:
            try:
                app_cfg.strategy.name = name
            except Exception:
                pass
        sp: dict[str, str] = {}
        for item in (cli_params or []):
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            sp[k.strip()] = v.strip()
        try:
            merged = dict(getattr(app_cfg.strategy, "params", {}) or {})
            merged.update(sp)
            app_cfg.strategy.params = merged
        except Exception:
            pass

    @staticmethod
    def emit_strategy_header(app_cfg: Any, logs_dir: _P, run_id: str) -> None:
        try:
            header = LiveRunner.build_header(app_ctx=None, config=app_cfg)
            write_event(
                logs_dir,
                {
                    "ts": int(time.time() * 1000),
                    "run_id": run_id,
                    "step": "run_header",
                    "strategy_name": header.strategy_name,
                    "strategy_cfg_hash": header.strategy_cfg_hash,
                    "strategy_params": header.params,
                },
            )
        except Exception:
            pass

    @staticmethod
    def export_resolved_from_yaml(runtime: Any, logger: logging.Logger, slog: Any) -> None:
        resolved: dict[str, str | float | int | bool] = {}
        warnings: list[dict] = []
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
                ("TESTNET", "true" if str(getattr(ex, "network", "testnet")).lower() == "testnet" else "false"),
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
                for w in warnings:
                    slog.log_info(ts=int(time.time() * 1000), symbol=None, tag="config:conflict", payload=w)  # type: ignore[arg-type]
            except Exception:
                pass
        try:
            slog.log_info(ts=int(time.time() * 1000), symbol=None, tag="config:resolved", payload=resolved)  # type: ignore[arg-type]
        except Exception:
            logger.info(f"config:resolved {resolved}")

    @staticmethod
    def apply_profile_overlay(runtime: Any, profile: str, logger: logging.Logger) -> bool:
        import yaml  # local import to avoid hard dep at module import time

        prof_name = "quick_test" if profile == "quick-test" else profile
        prof_path = _P(f"bot/configs/profiles/{prof_name}.yaml")
        if not prof_path.exists():
            return False
        with prof_path.open("r", encoding="utf-8") as f:
            overlay = yaml.safe_load(f) or {}
        def _merge_obj(obj, ov):
            for k, v in (ov or {}).items():
                if hasattr(obj, k) and not isinstance(v, dict):
                    setattr(obj, k, v)
                elif hasattr(obj, k) and isinstance(v, dict):
                    _merge_obj(getattr(obj, k), v)
        if overlay.get("exchange"):
            _merge_obj(runtime.app.exchange, overlay.get("exchange"))
        if overlay.get("risk"):
            _merge_obj(runtime.app.risk, overlay.get("risk"))
        if overlay.get("params"):
            _merge_obj(runtime.params, overlay.get("params"))
        if overlay.get("runtime"):
            _merge_obj(runtime.app.runtime, overlay.get("runtime"))
        logger.info(f"Applied profile overlay: {profile}")
        return True

    @staticmethod
    def refresh_universe(client: Any, runtime: Any, category: str, logger: logging.Logger):
        from bot.core.rotation import build_universe, Universe as _U  # local import

        uni_new = build_universe(
            client,
            topN=runtime.params.universe.topN,
            discover=bool(getattr(runtime.app.runtime, "discover_symbols", True)),
        )
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
        return _U(symbols=symbols_ref, discovered=uni_new.discovered)

    @staticmethod
    def load_instrument_filters(client: Any, category: str, symbol: str, logger: logging.Logger) -> dict:
        try:
            ins = client.get_instruments(category=category)
            flt = client.extract_symbol_filters(ins, symbol)
            logger.info(
                f"Instrument filters for {symbol}: tickSize={flt.get('tickSize')} qtyStep={flt.get('qtyStep')} minQty={flt.get('minOrderQty')}"
            )
            return flt
        except Exception as e:
            logger.warning(f"Failed to fetch instrument filters: {e}")
            return {"tickSize": None, "qtyStep": None, "minOrderQty": None}

    @staticmethod
    def set_leverage(client: Any, symbol: str, leverage: float, category: str, logger: logging.Logger) -> None:
        try:
            client.set_leverage(
                symbol=symbol,
                buyLeverage=int(leverage),
                sellLeverage=int(leverage),
                category=category,
            )
            logger.info("Leverage set OK")
        except Exception as e:  # covers BybitAPIError too
            if getattr(e, "ret_code", None) == 110043:
                logger.info("Leverage unchanged (110043): desired leverage already set")
            else:
                logger.warning(f"Set leverage failed: {e}")

    @staticmethod
    def get_orderbook_context(client: Any, *, symbol: str, category: str, ob_depth: int, logger: logging.Logger, slog: Any):
        ob = client.get_orderbook(symbol=symbol, depth=ob_depth, category=category)
        try:
            slog.log_info(
                ts=int(time.time() * 1000),
                symbol=symbol,
                tag="orderbook",
                payload=ob.get("result", {}),
            )
        except Exception:
            pass
        parse_ok = False
        mid = spread = bid_sz = ask_sz = obi = 0.0
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
            obi = ((bid_sz - ask_sz) / (bid_sz + ask_sz)) if (bid_sz + ask_sz) > 0 else 0.0
            parse_ok = True
        except Exception as e:
            logger.info(f"Failed to parse orderbook (fallback to ticker): {e}")
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
        return {
            "mid": mid,
            "spread": spread,
            "bid_sz": bid_sz,
            "ask_sz": ask_sz,
            "obi": obi,
            "parse_ok": parse_ok,
            "raw": ob,
        }

    @staticmethod
    def should_skip_for_open_position_or_orders(client: Any, *, category: str, symbol: str, logger: logging.Logger, slog: Any, loop_interval: float) -> bool:
        try:
            pos = client.get_position_info(category=category, symbol=symbol)
            long_size = 0.0
            short_size = 0.0
            try:
                it = (pos.get("result", {}).get("list", []) or [{}])[0]
                long_size = float(it.get("longSize") or 0)
                short_size = float(it.get("shortSize") or 0)
            except Exception:
                pass
            if long_size > 0 or short_size > 0:
                logger.info("Skip: existing position present (avoid duplicate)")
                try:
                    slog.log_why_no_trade(ts=int(time.time() * 1000), symbol=symbol, reasons=["skip_existing_position"], context={})
                except Exception:
                    pass
                time.sleep(loop_interval)
                return True
            try:
                oo = client.get_open_orders(symbol=symbol)
                raw_list = oo.get("result", {}).get("list", []) or []
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
                    logger.info(
                        f"OpenOrders(raw={len(raw_list)} filtered={len(olist)}): sample={olist[0] if olist else None}"
                    )
                if olist:
                    logger.info("Skip: open orders present for symbol (avoid duplicate)")
                    try:
                        slog.log_why_no_trade(
                            ts=int(time.time() * 1000),
                            symbol=symbol,
                            reasons=["skip_open_orders"],
                            context={"open_orders": len(olist)},
                        )
                    except Exception:
                        pass
                    time.sleep(loop_interval)
                    return True
            except Exception:
                pass
        except Exception:
            pass
        return False


def setup_loggers(run_id: str) -> tuple[logging.Logger, _P]:
    base_logs = _P("logs")
    base_logs.mkdir(parents=True, exist_ok=True)
    logs_dir = init_run_dir(base_logs, run_id)
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("live_testnet")
    logger.setLevel(logging.INFO)
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


def load_dotenv_if_present() -> int:
    """Load key=value pairs from repo-root `.env` if present.

    Does not override already-set env vars. Returns number of variables loaded.
    """
    try:
        env_fp = _P(__file__).resolve().parents[3] / ".env"
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
