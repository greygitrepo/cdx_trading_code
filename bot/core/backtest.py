"""Minimal backtester with partial fills, fees, and slippage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from .fees import FeeModel, SimpleFeeModel, SlippageModel, SimpleSlippage
from .types import Account, Fill, Order, OrderType, Side, Tick


@dataclass(slots=True)
class Engine:
    account: Account
    fee_model: FeeModel
    slippage: SlippageModel
    open_order: Optional[Order] = None
    fills: List[Fill] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:  # noqa: D401
        self.fills = []

    def place(self, order: Order) -> None:
        self.open_order = order

    def on_tick(self, tick: Tick, available_liquidity: float) -> None:
        if not self.open_order:
            return
        order = self.open_order

        # Determine if order is market or limit that is marketable
        marketable = False
        if order.type == OrderType.MARKET:
            marketable = True
        elif order.type == OrderType.LIMIT and order.limit_price is not None:
            if order.side == Side.BUY:
                marketable = order.limit_price >= tick.ask
            else:
                marketable = order.limit_price <= tick.bid

        filled_qty = 0.0
        fill_price = 0.0
        is_maker = False
        if marketable:
            filled_qty, fill_price, is_maker = self.slippage.fill(order.side, order.qty, tick, available_liquidity)
        else:
            # Maker: only fill if liquidity is zero (simulates resting and being picked off)
            filled_qty, fill_price, is_maker = self.slippage.fill(order.side, order.qty, tick, 0.0)

        if filled_qty > 0.0:
            notional = filled_qty * fill_price
            fee = self.fee_model.fee(notional, is_maker=is_maker)
            self.fills.append(
                Fill(ts=tick.ts, side=order.side, qty=filled_qty, price=fill_price, fee=fee, is_maker=is_maker)
            )
            self.account.position.update_on_fill(self.fills[-1])
            self.account.balance -= fee
            order.qty -= filled_qty
            if order.qty <= 1e-12 or (order.ioc and marketable):
                self.open_order = None

    def run(self, ticks: Iterable[Tick], liquidity: Iterable[float]) -> None:
        for tick, avail in zip(ticks, liquidity):
            self.on_tick(tick, avail)


def run_backtest() -> dict[str, int]:
    """Return simple backtest result for scaffolding."""
    acc = Account(balance=100.0)
    _ = Engine(account=acc, fee_model=SimpleFeeModel(), slippage=SimpleSlippage())
    # No orders placed in this trivial demo
    return {"trades": 0}
