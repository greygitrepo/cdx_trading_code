"""OB-Flow v2: Testnet live loop (minimal, safe by default)."""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path as _P, Path

# Ensure repo root on sys.path for direct execution
_ROOT = _P(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _import_runtime():
    # Import bot.* modules after sys.path injection to satisfy Ruff E402
    from bot.core.exchange.bybit_v5 import BybitV5Client, BybitAPIError
    from bot.core.book import L2Book, apply_snapshot, apply_delta
    from bot.core.data_ws import PublicWS
    from bot.core.features import basic_snapshot
    from bot.core.signals.obflow import decide, OBFlowConfig
    from bot.core.exec.broker import Broker, ExecConfig
    from bot.core.exec.risk import compute_tp_sl, RiskConfig
    from bot.core.recorder import Recorder

    return {
        "BybitV5Client": BybitV5Client,
        "BybitAPIError": BybitAPIError,
        "L2Book": L2Book,
        "apply_snapshot": apply_snapshot,
        "apply_delta": apply_delta,
        "PublicWS": PublicWS,
        "basic_snapshot": basic_snapshot,
        "decide": decide,
        "OBFlowConfig": OBFlowConfig,
        "Broker": Broker,
        "ExecConfig": ExecConfig,
        "compute_tp_sl": compute_tp_sl,
        "RiskConfig": RiskConfig,
        "Recorder": Recorder,
    }

def _round_step(v: float, step: float | None) -> float:
    if not step or step <= 0:
        return v
    return (int(v / step)) * step

def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() == "true"


def _env_clean(name: str, default: str) -> str:
    raw = os.environ.get(name, str(default))
    return (raw.split("#", 1)[0].strip()) if raw is not None else str(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_clean(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(_env_clean(name, str(default))))
    except Exception:
        return default

def _require_env_flags() -> None:
    live = os.environ.get("LIVE_MODE", "false").lower() == "true"
    testnet = os.environ.get("TESTNET", "false").lower() == "true"
    if not (live and testnet):
        print("Safety: TESTNET=true and LIVE_MODE=true required.")
        sys.exit(1)

def main() -> None:
    m = _import_runtime()
    BybitV5Client = m["BybitV5Client"]
    BybitAPIError = m["BybitAPIError"]
    L2Book = m["L2Book"]
    apply_snapshot = m["apply_snapshot"]
    apply_delta = m["apply_delta"]
    PublicWS = m["PublicWS"]
    basic_snapshot = m["basic_snapshot"]
    decide = m["decide"]
    OBFlowConfig = m["OBFlowConfig"]
    Broker = m["Broker"]
    ExecConfig = m["ExecConfig"]
    compute_tp_sl = m["compute_tp_sl"]
    RiskConfig = m["RiskConfig"]
    Recorder = m["Recorder"]
    _require_env_flags()
    if "DRY_RUN" not in os.environ:
        os.environ["DRY_RUN"] = "true"
    dry_run = _env_bool("DRY_RUN", True)
    symbol = os.environ.get("BYBIT_SYMBOL", "BTCUSDT").upper()
    logs_dir = Path("logs/obflow_live")
    rec = Recorder(logs_dir / "events.jsonl")
    client = BybitV5Client(testnet=True, category="linear")
    sg_bps = _env_float("SLIPPAGE_GUARD_BPS", -1.0)
    if sg_bps <= 0:
        sg_bps = _env_float("SLIPPAGE_GUARD_PCT", 0.0003) * 1e4
    broker = Broker(client, ExecConfig(slippage_guard_bps=sg_bps))
    risk_cfg = RiskConfig(tp_pct=_env_float("TP_PCT", 0.0045),
                          sl_pct=_env_float("SL_PCT", 0.0035),
                          time_stop_sec=_env_int("TIME_STOP_SEC", 5))
    ob_cfg = OBFlowConfig()
    qty_step = 0.001
    min_qty = 0.001
    try:
        ins = client.get_instruments(category=client.default_category)
        flt = client.extract_symbol_filters(ins, symbol)
        qty_step = float(flt.get("qtyStep") or qty_step)
        min_qty = float(flt.get("minOrderQty") or min_qty)
    except Exception:
        pass
    ws = PublicWS(symbol=symbol, depth=1)
    book = L2Book(symbol=symbol)
    start = time.time()
    max_sec = _env_float("MAX_SEC", 300.0)
    placed = 0
    for ev in ws.orderbook_stream():
        etype = ev.get("type")
        if etype == "snapshot":
            apply_snapshot(book,
                           int(ev.get("seq", 0)),
                           int(ev.get("ts", 0)),
                           ((float(p), float(s)) for p, s in ev.get("bids", [])),
                           ((float(p), float(s)) for p, s in ev.get("asks", [])))
        elif etype == "delta":
            ok = apply_delta(book,
                             int(ev.get("seq", 0)),
                             int(ev.get("ts", 0)),
                             ((float(p), float(s)) for p, s in ev.get("bids", [])),
                             ((float(p), float(s)) for p, s in ev.get("asks", [])))
            if not ok:
                continue
        else:
            continue
        feat = basic_snapshot(book)
        rec.write({"ts": int(time.time() * 1000), "event_type": "feature", "symbol": symbol, "features": feat})
        sig = decide(book, ob_cfg)
        if sig is None:
            if (time.time() - start) >= max_sec:
                break
            continue
        px = max(feat.get("mid") or 0.0, 1e-6)
        target = 10.0 / px
        qty = max(min_qty, _round_step(target, qty_step))
        tp, sl = compute_tp_sl(px, sig["side"], risk_cfg)
        rec.write({"ts": int(time.time() * 1000), "event_type": "signal_fire", "symbol": symbol,
                   "signal": sig, "qty": qty, "tp": tp, "sl": sl})
        if dry_run:
            continue
        try:
            res = broker.place_ioc(symbol, sig["side"], qty, ref_price=px)
            rec.write({"ts": int(time.time() * 1000), "event_type": "order_new", "symbol": symbol, "result": res})
            placed += 1
        except BybitAPIError as e:
            rec.write({"ts": int(time.time() * 1000), "event_type": "order_error", "symbol": symbol,
                       "error": str(e), "ret_code": getattr(e, "ret_code", None)})
        if (time.time() - start) >= max_sec:
            break
    print(f"OB-Flow live loop finished. Orders placed: {placed}, logs: {logs_dir}")

if __name__ == "__main__":
    main()
