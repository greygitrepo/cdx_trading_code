from typing import NamedTuple

class Fees(NamedTuple):
    taker_bps: float
    maker_bps: float

def net_pnl(entry_px: float, exit_px: float, qty: float, fees: Fees, taker_entry: bool = True, taker_exit: bool = True) -> float:
    gross = (exit_px - entry_px) * qty
    fee = 0.0
    if taker_entry:
        fee += entry_px * qty * (fees.taker_bps / 10000)
    if taker_exit:
        fee += exit_px * qty * (fees.taker_bps / 10000)
    return gross - fee

def tp_sl_trigger(pos, md, cfg) -> dict:
    mid = md["payload"]["mid"]
    entry = pos["entry_px"]
    tp_pct = cfg["risk"].get("tp_pct")
    sl_pct = cfg["risk"].get("sl_pct")
    change = (mid - entry) / entry
    if tp_pct is not None and change >= tp_pct:
        return {"should_exit": True, "reason": "tp"}
    if sl_pct is not None and change <= -sl_pct:
        return {"should_exit": True, "reason": "sl"}
    return {"should_exit": False, "reason": "hold"}

def will_enter(md, cfg) -> bool:
    spread = md["payload"].get("spread", 0.0)
    edge = md["payload"].get("edge", 0.0)
    max_spread = cfg.get("max_spread", float("inf"))
    min_edge = cfg.get("min_edge", 0.0)
    return spread <= max_spread and edge >= min_edge
