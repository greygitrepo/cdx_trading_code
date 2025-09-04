"""Market rules utility to fetch and cache symbol filters (tick/step/minimums).

Abstraction sits atop BybitV5Client but is simple enough to stub in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict

try:
    from bot.core.exchange.bybit_v5 import BybitV5Client
except Exception:  # pragma: no cover - lightweight fallback for tests
    BybitV5Client = object  # type: ignore


@dataclass
class MarketRule:
    symbol: str
    tick_size: Optional[float]
    lot_step: Optional[float]
    min_qty: Optional[float]
    min_notional: Optional[float] = None  # placeholder if exchange exposes


class MarketRules:
    def __init__(self, client: BybitV5Client):
        self.client = client
        self._cache: Dict[str, MarketRule] = {}

    def get(self, symbol: str) -> MarketRule:
        if symbol in self._cache:
            return self._cache[symbol]
        resp = self.client.get_instruments(category=self.client.default_category)
        flt = self.client.extract_symbol_filters(resp, symbol)
        rule = MarketRule(
            symbol=symbol,
            tick_size=flt.get("tickSize"),
            lot_step=flt.get("qtyStep"),
            min_qty=flt.get("minOrderQty"),
            min_notional=None,
        )
        self._cache[symbol] = rule
        return rule
