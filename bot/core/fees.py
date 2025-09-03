"""Fees and slippage models and simple implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .types import Side, Tick


class FeeModel(Protocol):
    def maker_rate(self) -> float:  # fraction, e.g., 0.0002
        ...

    def taker_rate(self) -> float:  # fraction, e.g., 0.00055
        ...

    def fee(self, notional: float, is_maker: bool) -> float:
        ...


@dataclass(slots=True)
class SimpleFeeModel:
    maker: float = 0.0002
    taker: float = 0.00055

    def maker_rate(self) -> float:
        return self.maker

    def taker_rate(self) -> float:
        return self.taker

    def fee(self, notional: float, is_maker: bool) -> float:
        rate = self.maker_rate() if is_maker else self.taker_rate()
        return abs(notional) * rate


class SlippageModel(Protocol):
    def fill(self, order_side: Side, qty: float, tick: Tick, available_liquidity: float) -> tuple[float, float, bool]:
        """Compute (filled_qty, fill_price, is_maker)."""
        ...


@dataclass(slots=True)
class SimpleSlippage:
    maker_bps: float = 0.0  # additional bps for maker; negative means price improvement
    taker_bps: float = 1.0  # 1 bps default taker slippage

    def _apply_bps(self, price: float, bps: float, side: Side) -> float:
        # bps in percentage (1 bps = 0.01%)
        factor = 1.0 + (bps / 10000.0)
        if side == Side.BUY:
            return price * factor
        return price / factor

    def fill(self, order_side: Side, qty: float, tick: Tick, available_liquidity: float) -> tuple[float, float, bool]:
        # For a BUY, hit ask (taker) or place at bid (maker). For SELL, inverse.
        taker_price = tick.ask if order_side == Side.BUY else tick.bid
        maker_price = tick.bid if order_side == Side.BUY else tick.ask
        # Apply configured slippage
        taker_price = self._apply_bps(taker_price, self.taker_bps, order_side)
        maker_price = self._apply_bps(maker_price, self.maker_bps, order_side)

        filled = min(qty, max(0.0, available_liquidity))
        # When taking liquidity, use taker_price; otherwise assume maker at quote
        is_maker = available_liquidity <= 0.0
        price = maker_price if is_maker else taker_price
        return filled, price, is_maker
