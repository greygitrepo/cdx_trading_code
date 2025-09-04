from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
import time
import math


@dataclass
class MarketRule:
    lot_step: float
    tick_size: float
    min_notional: float


class FakeExchangeClient:
    def __init__(self, rules: Dict[str, MarketRule], prices: Dict[str, float]):
        self.rules = rules
        self.prices = prices
        self.orders: list[dict] = []
        self.positions: dict[str, float] = {}

    def get_mark_price(self, symbol: str) -> float:
        return float(self.prices[symbol])

    def get_market_rules(self, symbol: str) -> MarketRule:
        return self.rules[symbol]

    def place_order(self, symbol: str, side: str, qty: float, price: float | None = None, reduce_only: bool = False):
        self.orders.append({"symbol": symbol, "side": side, "qty": qty, "reduce_only": reduce_only})
        if reduce_only:
            # Reduce-only adjusts in the specified side direction without flipping
            if side.lower() == "buy":
                self.positions[symbol] = round(self.positions.get(symbol, 0.0) + qty, 8)
            else:
                self.positions[symbol] = round(self.positions.get(symbol, 0.0) - qty, 8)
        else:
            signed = qty if side.lower() == "buy" else -qty
            self.positions[symbol] = round(self.positions.get(symbol, 0.0) + signed, 8)
        return {"status": "filled", "order_id": f"fake_{len(self.orders)}"}

    # helper-like methods to mimic testnet client
    def get_position_size(self, symbol: str) -> float:
        return float(self.positions.get(symbol, 0.0))

    def close_position(self, symbol: str) -> None:
        sz = self.positions.get(symbol, 0.0)
        if sz == 0:
            return
        side = "sell" if sz > 0 else "buy"
        self.place_order(symbol, side, abs(sz), reduce_only=True)


class StubClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)


def round_by_step(x: float, step: float) -> float:
    return math.floor(x / step) * step
