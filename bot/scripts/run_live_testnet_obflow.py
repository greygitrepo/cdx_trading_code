"""OB-Flow v2: Testnet live loop (minimal, safe by default)."""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path
from bot.core.exchange.bybit_v5 import BybitV5Client, BybitAPIError
from bot.core.book import L2Book, apply_snapshot, apply_delta
from bot.core.data_ws import PublicWS
from bot.core.features import basic_snapshot
from bot.core.signals.obflow import decide, OBFlowConfig
from bot.core.exec.broker import Broker, ExecConfig
from bot.core.exec.risk import compute_tp_sl, RiskConfig
from bot.core.recorder import Recorder

def _round_step(v: float, step: float | None) -> float:
    if not step or step <= 0:
        return v
    return (int(v / step)) * step

def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() == "true"

def _require_env_flags() -> None:
    live = os.environ.get("LIVE_MODE", "false").lower() == "true"
    testnet = os.environ.get("TESTNET", "false").lower() == "true"
    if not (live and testnet):
        print("Safety: TESTNET=true and LIVE_MODE=true required.")
        sys.exit(1)

def main() -> None:
    _require_env_flags()
    if "DRY_RUN" not in os.environ:
        os.environ["DRY_RUN"] = "true"
    dry_run = _env_bool("DRY_RUN", True)
    symbol = os.environ.get("BYBIT_SYMBOL", "BTCUSDT").upper()
    logs_dir = Path("logs/obflow_live")
    rec = Recorder(logs_dir / "events.jsonl")
    client = BybitV5Client(testnet=True, category="linear")
    broker = Broker(client, ExecConfig(slippage_guard_bps=float(os.environ.get("SLIPPAGE_GUARD_BPS", "3") or 3)))
    risk_cfg = RiskConfig(tp_pct=float(os.environ.get("TP_PCT", "0.0045") or 0.0045),
                          sl_pct=float(os.environ.get("SL_PCT", "0.0035") or 0.0035),
                          time_stop_sec=int(float(os.environ.get("TIME_STOP_SEC", "5") or 5)))
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
    max_sec = float(os.environ.get("MAX_SEC", "300") or 300)
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
