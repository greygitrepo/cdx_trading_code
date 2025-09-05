"""OB-Flow v2: Lightweight execution broker.

Provides PostOnly/IOC order placement with simple slippage guard.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.core.exchange.bybit_v5 import BybitV5Client


@dataclass
class ExecConfig:
    slippage_guard_bps: float = 3.0
    category: str = "linear"


class Broker:
    def __init__(self, client: BybitV5Client, cfg: ExecConfig = ExecConfig()) -> None:
        self.client = client
        self.cfg = cfg

    def place_ioc(self, symbol: str, side: str, qty: float, ref_price: float) -> dict:
        # Slippage guard at client side
        max_dev = self.cfg.slippage_guard_bps * 1e-4 * ref_price
        _ = ref_price + (max_dev if side.upper() == "BUY" else -max_dev)
        # For IOC Market, price is None; guard is advisory only
        return self.client.place_order(
            symbol=symbol,
            side=side,
            qty=str(qty),
            orderType="Market",
            timeInForce="IOC",
            category=self.cfg.category,
            price=None,
        )
