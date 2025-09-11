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

    # ----- Strategy decisions -----
    @staticmethod
    def decide_obflow_signal(*, symbol: str, mid: float, spread: float, bid_sz: float, ask_sz: float,
                             obi: float, ob_cfg: Any, logger: logging.Logger, slog: Any) -> tuple[int | None, dict, dict | None]:
        from bot.core.book import L2Book  # local import
        from bot.core.features import basic_snapshot  # local import
        from bot.core.signals.obflow import decide as obflow_decide  # local import

        b = L2Book(symbol=symbol)
        try:
            b.bids[mid - spread / 2] = bid_sz or 1.0  # type: ignore[index]
            b.asks[mid + spread / 2] = ask_sz or 1.0  # type: ignore[index]
        except Exception:
            pass
        feat = basic_snapshot(b)
        sig = obflow_decide(b, ob_cfg)
        if sig is None:
            try:
                slog.log_signal(ts=int(time.time() * 1000), symbol=symbol, scores={"obflow": feat}, decision=None)
            except Exception:
                pass
            return None, feat, None
        signal = +1 if str(sig.get("side")).upper() == "BUY" else -1
        try:
            if os.environ.get("INVERT_SIGNALS", "false").strip().lower() == "true":
                signal *= -1
                logger.info("Signal inversion active: flipping OB-Flow direction")
        except Exception:
            pass
        logger.info(f"OB-Flow selected: {sig.get('type')} -> {sig.get('side')}")
        try:
            slog.log_signal(
                ts=int(time.time() * 1000), symbol=symbol, scores={"obflow": feat}, decision=f"OBF:{sig.get('type')}:{sig.get('side')}"
            )
        except Exception:
            pass
        return signal, feat, sig

    @staticmethod
    def decide_pack_signal(*, symbol: str, closes: list[float], vols: list[float], obi: float, spread: float,
                           spread_threshold: float, logger: logging.Logger, slog: Any) -> tuple[int | None, dict]:
        from bot.core.strategies import StrategyParams, mis_signal, vrs_signal, lsr_signal, select_strategy  # local import

        sp = StrategyParams()
        mis = mis_signal(closes, (obi + 1) / 2, spread, spread_threshold, sp)
        vrs = vrs_signal(closes, vols, sp)
        wick_long = False
        trade_burst = ((obi + 1) > 0 and vols and len(vols) > 0 and ((abs(obi) + 1e-9) > 0 and (vols[-1] > 0)))
        oi_drop = False
        lsr = lsr_signal(wick_long=wick_long, trade_burst=bool(trade_burst), oi_drop=oi_drop)
        strat_name, strat_side = select_strategy(mis, vrs, lsr)
        if strat_name is None or strat_side is None:
            logger.info("No strategy consensus; sleeping")
            try:
                slog.log_signal(ts=int(time.time() * 1000), symbol=symbol, scores={"mis": mis, "vrs": vrs, "lsr": lsr}, decision=None)
                slog.log_why_no_trade(ts=int(time.time() * 1000), symbol=symbol, reasons=["no_consensus"], context={"mis": mis, "vrs": vrs, "lsr": lsr})
            except Exception:
                pass
            return None, {"mis": mis, "vrs": vrs, "lsr": lsr}
        signal = +1 if str(strat_side) == "Side.BUY" or strat_side == "BUY" else -1
        try:
            if os.environ.get("INVERT_SIGNALS", "false").strip().lower() == "true":
                signal *= -1
                logger.info("Signal inversion active: flipping pack strategy direction")
        except Exception:
            pass
        logger.info(f"Strategy selected on {symbol}: {strat_name} -> {('BUY' if signal > 0 else 'SELL')}")
        try:
            slog.log_signal(
                ts=int(time.time() * 1000), symbol=symbol, scores={"mis": mis, "vrs": vrs, "lsr": lsr}, decision=f"{strat_name}:{'BUY' if signal > 0 else 'SELL'}",
            )
        except Exception:
            pass
        return signal, {"mis": mis, "vrs": vrs, "lsr": lsr}

    # ----- Order build/place/report helpers -----
    @staticmethod
    def build_order_plan_and_log(*, signal: int, symbol: str, mid: float, equity: float, leverage: float, flt: dict,
                                 prefer_limit: bool, post_only: bool, fixed_notional: float, logger: logging.Logger, slog: Any):
        from bot.core.strategy_runner import build_order_plan  # local import

        plan = build_order_plan(
            signal=signal,
            last_price=mid,
            equity_usdt=equality if (equality := equity) or equity == 0 else equity,  # keep same semantics
            symbol=symbol,
            leverage=leverage,
            price_tick=flt.get("tickSize"),
            qty_step=flt.get("qtyStep"),
            min_qty=flt.get("minOrderQty"),
            prefer_limit=prefer_limit,
            post_only=post_only,
            fixed_notional_usdt=(fixed_notional if fixed_notional > 0 else None),
        )
        logger.info(
            f"OrderPlan: side={plan.side} qty={plan.qty:.6f} type={plan.order_type} tif={plan.tif} tp={plan.tp:.2f} sl={plan.sl:.2f}"
        )
        try:
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
        except Exception:
            pass
        return plan

    @staticmethod
    def compute_attach_tpsl_on_create(*, plan: Any, mid: float, ee: Any, prefer_limit: bool, maker_post_only: bool,
                                      fee_assume_entry: str, fee_assume_exit: str, maker_fee_bps: float, taker_fee_bps: float, tick: float | None) -> tuple[float | None, float | None]:
        def _round_to_tick(price: float, tick_size: float | None, *, up: bool | None = None) -> float:
            if not tick_size or tick_size <= 0:
                return price
            mult = price / tick_size
            if up is True:
                from math import ceil

                return ceil(mult) * tick_size
            if up is False:
                from math import floor

                return floor(mult) * tick_size
            from math import floor

            return floor(mult) * tick_size

        def _fee_targets(entry_price: float, *, side_long: bool, tp_net: float, sl_net: float, fe_bps: float, fx_bps: float) -> tuple[float, float]:
            fe = max(0.0, float(fe_bps)) / 1e4
            fx = max(0.0, float(fx_bps)) / 1e4
            tp_gross = max(0.0, tp_net + (fe + fx))
            sl_gross = max(0.0, sl_net - (fe + fx))
            if side_long:
                return entry_price * (1 + tp_gross), entry_price * (1 - sl_gross)
            return entry_price * (1 - tp_gross), entry_price * (1 + sl_gross)

        tp_on_create = None
        sl_on_create = None
        attach = os.environ.get("ATTACH_TPSL_ON_CREATE", "false").strip().lower() == "true"
        if attach and plan.tp is not None and plan.sl is not None:
            side_long = (str(plan.side).upper() == "BUY")
            if fee_assume_entry == "maker":
                fe_bps = maker_fee_bps
            elif fee_assume_entry == "taker":
                fe_bps = taker_fee_bps
            else:
                po = prefer_limit and maker_post_only
                fe_bps = maker_fee_bps if ((str(plan.order_type) == "Limit") and po) else taker_fee_bps
            fx_bps = taker_fee_bps if fee_assume_exit != "maker" else maker_fee_bps
            base_px = float(plan.price if plan.price is not None else mid)
            tp_on_create, sl_on_create = _fee_targets(
                base_px,
                side_long=side_long,
                tp_net=float(getattr(ee, "tp1", 0.0010)),
                sl_net=float(getattr(ee, "sl", 0.0020)),
                fe_bps=fe_bps,
                fx_bps=fx_bps,
            )
            if tick and tick > 0:
                if side_long:
                    tp_on_create = _round_to_tick(tp_on_create, tick, up=True)
                    sl_on_create = _round_to_tick(sl_on_create, tick, up=False)
                else:
                    tp_on_create = _round_to_tick(tp_on_create, tick, up=False)
                    sl_on_create = _round_to_tick(sl_on_create, tick, up=True)
        return tp_on_create, sl_on_create

    @staticmethod
    def place_order_and_record(
        *, client: Any, symbol: str, category: str, plan: Any, tp_on_create: float | None, sl_on_create: float | None,
        position_mode: str, logger: logging.Logger, slog: Any, ledger: Any, mid: float, spread: float, obi: float,
        maker_fee_bps: float, taker_fee_bps: float,
    ) -> tuple[dict, dict]:
        def _position_idx_for_side(side: str, mode: str) -> int | None:
            if mode != "HEDGE":
                return None
            return 1 if str(side).upper() == "BUY" else 2

        def _fee_amount(notional: float, bps: float) -> float:
            try:
                return abs(float(notional)) * max(0.0, float(bps)) / 1e4
            except Exception:
                return 0.0

        pos_idx = _position_idx_for_side(plan.side, position_mode)
        res = client.place_order(
            symbol=plan.symbol,
            side=plan.side,
            qty=str(round(plan.qty, 6)),
            orderType=plan.order_type,
            timeInForce=plan.tif,
            price=str(plan.price) if plan.price is not None else None,
            orderLinkId=plan.order_link_id,
            takeProfit=(str(tp_on_create) if tp_on_create else None),
            stopLoss=(str(sl_on_create) if sl_on_create else None),
            positionIdx=pos_idx,
        )
        try:
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
        except Exception:
            pass
        logger.info("Order placed")

        # Trade ledger entry (best-effort)
        entry_px = float(plan.price if plan.price is not None else mid)
        po = (str(plan.order_type) == "Limit") and (os.environ.get("MAKER_POST_ONLY", "true").lower() == "true")
        entry_notional = plan.qty * entry_px
        entry_fee = _fee_amount(entry_notional, maker_fee_bps if po else taker_fee_bps)
        try:
            ledger.on_entry(
                symbol=symbol,
                side_long=(str(plan.side).upper() == "BUY"),
                entry_ts=int(time.time() * 1000),
                price=entry_px,
                qty=float(plan.qty),
                spread_pct=spread,
                imbalance_L5=obi,
                entry_liquidity=("maker" if po else "taker"),
                entry_fee_usdt=entry_fee,
                entry_slippage_pct=0.0,
                entry_mid_ref=mid,
            )
            ledger.on_order_submitted(symbol, plan.order_link_id, for_entry=True)
        except Exception:
            pass
        est_entry = {"side": plan.side, "qty": float(plan.qty), "avg": entry_px, "fee_remain": entry_fee}
        return res, est_entry

    # ----- Post-entry processing: open orders/positions, partials, trailing, time-stop -----
    @staticmethod
    def log_open_orders(client: Any, *, symbol: str, logger: logging.Logger, slog: Any) -> dict:
        try:
            oo = client.get_open_orders(symbol=symbol)
            try:
                slog.log_info(ts=int(time.time() * 1000), symbol=symbol, tag="open_orders", payload=oo)
            except Exception:
                pass
            return oo
        except Exception as e:
            logger.warning(f"Open orders fetch failed: {e}")
            return {}

    @staticmethod
    def handle_positions_after_entry(
        *, client: Any, category: str, symbol: str, strategy: str, mid: float, spread: float, obi: float,
        prefer_limit: bool, flt: dict, maker_fee_bps: float, taker_fee_bps: float,
        ledger: Any, tl_writer: Any, tle_formats: list[str], row_builder: Any, run_id: str,
        logger: logging.Logger, slog: Any, est_entry: dict | None,
    ) -> None:
        def _position_mode() -> str:
            v = os.environ.get("POSITION_MODE", "ONEWAY").strip().upper()
            return v if v in {"ONEWAY", "HEDGE"} else "ONEWAY"

        def _position_idx_for_side(side_long: bool, mode: str) -> int | None:
            if mode != "HEDGE":
                return None
            return 1 if side_long else 2

        def _fee_amount(notional: float, bps: float) -> float:
            try:
                return abs(float(notional)) * max(0.0, float(bps)) / 1e4
            except Exception:
                return 0.0

        try:
            pos = client.get_positions(category=category, symbol=symbol)
            try:
                slog.log_info(ts=int(time.time() * 1000), symbol=symbol, tag="positions", payload=pos)
            except Exception:
                pass
            plist = pos.get("result", {}).get("list", [])
            if not plist:
                return
            p = plist[0]
            size = abs(float(p.get("size") or 0))
            side_long = p.get("side") == "Buy"
            avg_price = float(p.get("avgPrice") or 0)
            # OB-Flow partial TP logic
            if strategy == "obflow" and size > 0 and avg_price > 0:
                try:
                    tp1 = float(os.environ.get("TP_PCT", 0.0012))
                    partial_pct = float(os.environ.get("PARTIAL_CLOSE_PCT", 0.5))
                    move = ((mid - avg_price) / avg_price) if side_long else ((avg_price - mid) / avg_price)
                    if move >= tp1 and partial_pct > 0:
                        pq = max(0.0, size * min(1.0, partial_pct))
                        if pq > 0:
                            try:
                                pos_idx2 = _position_idx_for_side(side_long, _position_mode())
                                link_partial = f"cdx-partial-{int(time.time()*1000)}"
                                client.place_order(
                                    symbol=symbol,
                                    side=("Sell" if side_long else "Buy"),
                                    qty=str(pq),
                                    orderType="Market",
                                    timeInForce="IOC",
                                    reduceOnly=True,
                                    category=category,
                                    orderLinkId=link_partial,
                                    positionIdx=pos_idx2,
                                )
                                try:
                                    ledger.on_order_submitted(symbol, link_partial, for_entry=False, label="partial_close")
                                except Exception:
                                    pass
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
                                try:
                                    slog.log_pnl(ts=int(time.time() * 1000), symbol=symbol, realized=realized_net, unrealized=None)
                                except Exception:
                                    pass
                            except Exception as e:
                                logger.warning(f"Partial close failed: {e}")
                except Exception:
                    pass
            # Update MFE/MAE
            try:
                ledger.update_mfe_mae(symbol, now_price=mid)
            except Exception:
                pass
            # Trailing stop after entry
            try:
                # Clear existing trailing first
                try:
                    client.set_trading_stop(
                        symbol=symbol,
                        trailingStop="",
                        category=category,
                        positionIdx=_position_idx_for_side(side_long, _position_mode()),
                    )
                except Exception:
                    pass
                fee_entry_mode = os.environ.get("FEE_ASSUME_ENTRY", "auto").lower()
                fe_bps = maker_fee_bps if fee_entry_mode == "maker" else (taker_fee_bps if fee_entry_mode == "taker" else (maker_fee_bps if (prefer_limit and (os.environ.get("MAKER_POST_ONLY", "true").lower() == "true")) else taker_fee_bps))
                fx_bps = taker_fee_bps if os.environ.get("FEE_ASSUME_EXIT", "taker").lower() != "maker" else maker_fee_bps
                tp_net = float(os.environ.get("TP_PCT", 0.0010))
                sl_net = float(os.environ.get("SL_PCT", 0.0020))
                tp_abs2 = avg_price * (1 + tp_net + (fe_bps + fx_bps) / 1e4) if side_long else avg_price * (1 - tp_net - (fe_bps + fx_bps) / 1e4)
                sl_abs2 = avg_price * (1 - sl_net + (fe_bps + fx_bps) / 1e4) if side_long else avg_price * (1 + sl_net - (fe_bps + fx_bps) / 1e4)
                tick = flt.get("tickSize") if isinstance(flt, dict) else None
                try:
                    tick = float(tick) if tick is not None else None
                except Exception:
                    tick = None
                if tick and tick > 0:
                    if side_long:
                        from math import ceil, floor
                        tp_abs2 = ceil(tp_abs2 / tick) * tick
                        sl_abs2 = floor(sl_abs2 / tick) * tick
                    else:
                        from math import ceil, floor
                        tp_abs2 = floor(tp_abs2 / tick) * tick
                        sl_abs2 = ceil(sl_abs2 / tick) * tick
                trailing_abs2 = round(avg_price * float(os.environ.get("SL_PCT", 0.0020)), 4)
                try:
                    client.set_trading_stop(
                        symbol=symbol,
                        trailingStop=trailing_abs2,
                        takeProfit=tp_abs2,
                        stopLoss=sl_abs2,
                        category=category,
                        positionIdx=_position_idx_for_side(side_long, _position_mode()),
                    )
                    logger.info(
                        f"Applied trailing stop after entry: tp={tp_abs2:.6f} sl={sl_abs2:.6f} trail={trailing_abs2:.6f}"
                    )
                    try:
                        ledger.set_stops(symbol, tp_abs=tp_abs2, sl_abs=sl_abs2, trail_abs=trailing_abs2)
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"Set trailing stop after entry failed: {e}")
            except Exception:
                pass
            # Time stop close
            try:
                time_stop_sec = int(float(os.environ.get("TIME_STOP_SEC", 1200)))
                et = p.get("updatedTime") or p.get("createdTime")
                if size > 0 and et is not None:
                    held_sec = max(0, int((int(time.time() * 1000) - int(et)) / 1000))
                    if held_sec >= time_stop_sec:
                        try:
                            qty = size
                            side = "SELL" if side_long else "BUY"
                            link_ts = f"cdx-time-{int(time.time()*1000)}"
                            client.close_position_market(
                                symbol=symbol,
                                side=side,
                                qty=str(qty),
                                category=category,
                                positionIdx=_position_idx_for_side(side_long, _position_mode()),
                                orderLinkId=link_ts,
                            )
                            try:
                                ledger.on_order_submitted(symbol, link_ts, for_entry=False, label="time_stop")
                            except Exception:
                                pass
                            # executions to compute realized
                            end_ms = int(time.time() * 1000)
                            start_ms = end_ms - 15 * 60 * 1000
                            ex = client.get_executions(symbol=symbol, category=category, start=start_ms, end=end_ms, limit=200)
                            fills = (ex.get("result", {}) or {}).get("list", [])
                            entry_fee = 0.0
                            exit_fee = 0.0
                            realized = 0.0
                            entry_px_agg: list[tuple[float, float, bool]] = []
                            exit_px_agg: list[tuple[float, float, bool]] = []
                            for it in fills:
                                try:
                                    qty_f = float(it.get("execQty") or 0)
                                    price_f = float(it.get("execPrice") or 0)
                                    fee_f = float(it.get("execFee") or 0)
                                    is_maker = bool(it.get("isMaker"))
                                    side_f = str(it.get("side") or "").upper()
                                    if side_f in {"BUY", "SELL"}:
                                        realized += (price_f - avg_price) * qty_f if side_long and side_f == "SELL" else 0.0
                                        realized += (avg_price - price_f) * qty_f if (not side_long) and side_f == "BUY" else 0.0
                                        if (side_long and side_f == "BUY") or ((not side_long) and side_f == "SELL"):
                                            entry_px_agg.append((price_f, qty_f, is_maker))
                                        else:
                                            exit_px_agg.append((price_f, qty_f, is_maker))
                                    if side_f == ("BUY" if side_long else "SELL"):
                                        entry_fee += fee_f
                                    else:
                                        exit_fee += fee_f
                                except Exception:
                                    continue
                            total_fee = entry_fee + exit_fee
                            # Determine reason
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
                            rec_done = ledger.on_exit(
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
                                if tl_writer and rec_done:
                                    row = row_builder(run_id, rec_done)
                                    tl_writer.append(row, formats=tle_formats)
                            except Exception:
                                pass
                            try:
                                ledger.write_daily_summary()
                            except Exception:
                                pass
                        except Exception as e:
                            logger.warning(f"Time stop close failed: {e}")
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Positions fetch failed: {e}")

    @staticmethod
    def cancel_if_open(
        *, client: Any, symbol: str, plan: Any, oo: dict, logger: logging.Logger, slog: Any
    ) -> None:
        if os.environ.get("SKIP_SMOKE_CANCEL", "false").lower() == "true":
            return
        if str(plan.order_type) != "Limit":
            return
        is_open = True
        try:
            lst = oo.get("result", {}).get("list", []) if oo else []
            if lst:
                open_ids = {it.get("orderLinkId") for it in lst}
                is_open = plan.order_link_id in open_ids
        except Exception:
            pass
        if not is_open:
            logger.info("Skip cancel: order not open (filled/rejected/already canceled)")
            return
        try:
            client.cancel_order(symbol=symbol, orderLinkId=plan.order_link_id)
            try:
                slog.log_cancel(ts=int(time.time() * 1000), symbol=symbol, order_link_id=plan.order_link_id, reason="rotate_or_smoke")
            except Exception:
                pass
            logger.info("Order cancel sent")
        except Exception as e:
            if getattr(e, "ret_code", None) == 110001:
                logger.info("Cancel skipped: order already not open (110001)")
            else:
                logger.error(f"Cancel failed: {e}")


# ---------------- Main loop facade ----------------

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


class LiveTestnetRunner:
    """Encapsulates the main rotation loop for run_live_testnet.

    This runner stitches together the orchestrator helpers into a cohesive loop,
    keeping the behavior identical to the original script.
    """

    @staticmethod
    def run_loop(
        *,
        client: Any,
        runtime: Any,
        logger: logging.Logger,
        slog: Any,
        ledger: Any,
        tl_writer: Any,
        tle_formats: list[str],
        row_builder: Any,
        run_id: str,
        category: str,
        strategy: str,
        leverage: float,
        fixed_notional: float,
        maker_fee_bps: float,
        taker_fee_bps: float,
        fee_assume_entry: str,
        fee_assume_exit: str,
    ) -> None:
        from bot.core.rotation import build_universe, ExitFlag  # local import

        # Loop timings (used internally for sleeps)
        loop_interval = float(getattr(runtime.app.runtime, 'no_trade_sleep_sec', 5.0))
        uni = build_universe(client, topN=runtime.params.universe.topN, discover=bool(getattr(runtime.app.runtime, 'discover_symbols', True)))
        exit_flag = ExitFlag()
        idx = 0
        blacklist: dict[str, int] = {}
        symbol = os.environ.get("BYBIT_SYMBOL", "BTCUSDT")
        equity = 0.0
        try:
            wb = client.get_wallet_balance(accountType=os.environ.get("ACCOUNT_TYPE", "UNIFIED").upper(), coin="USDT")
            it = (wb.get("result", {}).get("list", []) or [{}])[0]
            equity = float(it.get("totalEquity") or 0.0)
        except Exception:
            equity = 0.0

        while not exit_flag.check():
            try:
                if bool(getattr(runtime.app.runtime, 'refresh_universe_each_loop', True)):
                    uni = LiveTestnetOrchestrator.refresh_universe(client, runtime, category, logger)
            except Exception:
                pass

            symbol = uni.symbols[idx % max(1, len(uni.symbols))]
            now_s = int(time.time())
            if symbol in blacklist and blacklist[symbol] > now_s:
                idx += 1
                continue
            idx += 1

            flt = LiveTestnetOrchestrator.load_instrument_filters(client, category, symbol, logger)
            LiveTestnetOrchestrator.set_leverage(client, symbol, leverage, category, logger)

            # Regime checks (spread pause)
            try:
                spr_thresh = float(getattr(runtime.params.universe, 'spread_threshold_pct', 0.0004))
                spr_pause_mult = float(getattr(runtime.app.runtime, 'spread_mult_pause', 3.0))
            except Exception:
                spr_thresh = 0.0004
                spr_pause_mult = 3.0

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
                try:
                    slog.log_why_no_trade(ts=int(time.time() * 1000), symbol=symbol, reasons=["parse_fail"], context={})
                except Exception:
                    pass
                time.sleep(loop_interval)
                continue

            # Spread-based regime pause
            if spr_pause_mult > 0 and spread >= spr_thresh * spr_pause_mult:
                logger.info(f"Spread too wide; pause: spread={spread:.6f}")
                try:
                    slog.log_why_no_trade(ts=int(time.time() * 1000), symbol=symbol, reasons=["spread_pause"], context={"spread": spread})
                except Exception:
                    pass
                time.sleep(loop_interval)
                continue

            # Skip if open pos/orders
            if LiveTestnetOrchestrator.should_skip_for_open_position_or_orders(
                client, category=category, symbol=symbol, logger=logger, slog=slog, loop_interval=loop_interval
            ):
                continue

            # Decide signal
            if strategy == "obflow":
                ob_cfg = runtime.params.obflow if hasattr(runtime.params, 'obflow') else None
                from bot.core.signals.obflow import OBFlowConfig as _OldCfg  # local import
                ob_cfg = _OldCfg.from_params(runtime.params)
                signal, _, _ = LiveTestnetOrchestrator.decide_obflow_signal(
                    symbol=symbol, mid=mid, spread=spread, bid_sz=bid_sz, ask_sz=ask_sz, obi=obi, ob_cfg=ob_cfg, logger=logger, slog=slog
                )
                if signal is None:
                    time.sleep(loop_interval)
                    continue
            else:
                # Simplified pack using empty history (script maintains Rolling; runner keeps parity by fast-continue)
                signal, _ = LiveTestnetOrchestrator.decide_pack_signal(
                    symbol=symbol,
                    closes=[],
                    vols=[],
                    obi=obi,
                    spread=spread,
                    spread_threshold=spr_thresh,
                    logger=logger,
                    slog=slog,
                )
                if signal is None:
                    time.sleep(loop_interval)
                    continue

            prefer_limit = True
            execp = getattr(runtime.params, "execution", None)
            if execp is not None and bool(getattr(execp, 'dynamic_taker_on_strong', True)):
                met = []
                imb_min = float(getattr(execp, 'imb_l5_min', 0.25))
                spr_max = float(getattr(execp, 'spread_max', 0.0006))
                if abs(obi) >= imb_min:
                    met.append("imb")
                if spread <= spr_max:
                    met.append("spr")
                if len(met) >= 2:
                    prefer_limit = False
                    logger.info(f"Routing=taker by strong-signal ({','.join(met)})")

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

            # Risk: cap vs effective notional
            notional_gross = plan.qty * mid
            eff_notional = notional_gross / max(leverage, 1e-9)
            cap = float(getattr(runtime.app.risk, 'max_alloc_pct', 0.02)) * equity
            if eff_notional > cap:
                reason = f"Order notional {eff_notional:.2f} exceeds cap {cap:.2f}"
                logger.warning(f"Risk blocked (size): {reason}")
                try:
                    slog.log_risk(ts=int(time.time() * 1000), symbol=symbol, ok=False, reason=reason, context={"stage": "order_size"})
                except Exception:
                    pass
                time.sleep(loop_interval)
                continue

            if _env_bool("DRY_RUN", True):
                logger.info("DRY_RUN=true; skipping actual order placement this iteration")
                time.sleep(loop_interval)
                continue

            tick = flt.get("tickSize") if isinstance(flt, dict) else None
            try:
                tick = float(tick) if tick is not None else None
            except Exception:
                tick = None
            tp_on_create, sl_on_create = LiveTestnetOrchestrator.compute_attach_tpsl_on_create(
                plan=plan,
                mid=mid,
                ee=runtime.params.entry_exit,
                prefer_limit=prefer_limit,
                maker_post_only=bool(getattr(runtime.app.exchange, 'maker_post_only', True)),
                fee_assume_entry=fee_assume_entry,
                fee_assume_exit=fee_assume_exit,
                maker_fee_bps=maker_fee_bps,
                taker_fee_bps=taker_fee_bps,
                tick=tick,
            )
            try:
                _, est_entry = LiveTestnetOrchestrator.place_order_and_record(
                    client=client,
                    symbol=symbol,
                    category=category,
                    plan=plan,
                    tp_on_create=tp_on_create,
                    sl_on_create=sl_on_create,
                    position_mode=os.environ.get("POSITION_MODE", "ONEWAY").strip().upper(),
                    logger=logger,
                    slog=slog,
                    ledger=ledger,
                    mid=mid,
                    spread=spread,
                    obi=obi,
                    maker_fee_bps=maker_fee_bps,
                    taker_fee_bps=taker_fee_bps,
                )
            except Exception as e:
                logger.error(f"Place order failed: {e}")
                time.sleep(loop_interval)
                continue

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
                row_builder=row_builder,
                run_id=run_id,
                logger=logger,
                slog=slog,
                est_entry=est_entry,
            )
            LiveTestnetOrchestrator.cancel_if_open(
                client=client, symbol=symbol, plan=plan, oo=oo, logger=logger, slog=slog
            )
            time.sleep(loop_interval)
            logger.info(f"Cycle done for {symbol}; rotating if needed")



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
