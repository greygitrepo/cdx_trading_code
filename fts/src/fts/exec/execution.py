import random

from ..common.types import Event, Signal


def execute_trade(event: Event, signal: Signal) -> float:
    entry = event.price
    tp = signal.tp_bps / 10000
    sl = signal.sl_bps / 10000
    win = random.random() < 0.8
    if win:
        exit_price = entry * (1 - tp) if signal.side == "SELL" else entry * (1 + tp)
    else:
        exit_price = entry * (1 + sl) if signal.side == "SELL" else entry * (1 - sl)
    pnl = (entry - exit_price) if signal.side == "SELL" else (exit_price - entry)
    return pnl
