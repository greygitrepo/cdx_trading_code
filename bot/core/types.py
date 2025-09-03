"""Common typed models for timeseries, orders, fills, positions, and accounts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass(slots=True)
class Tick:
    ts: int  # epoch ms
    bid: float
    ask: float
    last: float
    bid_sz: float = 0.0
    ask_sz: float = 0.0


@dataclass(slots=True)
class Order:
    side: Side
    qty: float
    type: OrderType
    limit_price: Optional[float] = None
    post_only: bool = False
    ioc: bool = False
    reduce_only: bool = False


@dataclass(slots=True)
class Fill:
    ts: int
    side: Side
    qty: float
    price: float
    fee: float
    is_maker: bool


@dataclass(slots=True)
class Position:
    side: Optional[Side] = None
    qty: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0

    def update_on_fill(self, fill: Fill) -> None:
        # Opening or adding
        if self.qty == 0.0:
            self.side = fill.side
            self.qty = fill.qty
            self.avg_price = fill.price
        elif self.side == fill.side:
            new_qty = self.qty + fill.qty
            self.avg_price = (self.avg_price * self.qty + fill.price * fill.qty) / new_qty
            self.qty = new_qty
        else:
            # Closing or flipping
            close_qty = min(self.qty, fill.qty)
            pnl_per_unit = (self.avg_price - fill.price) if self.side == Side.SELL else (fill.price - self.avg_price)
            self.realized_pnl += pnl_per_unit * close_qty
            self.qty -= close_qty
            if self.qty == 0.0:
                self.side = None
                self.avg_price = 0.0
            else:
                # Remaining qty flips or maintains partially closed; set avg price to fill price for flipped remainder
                if fill.qty > close_qty:
                    # flipped: remainder in fill side direction
                    remainder = fill.qty - close_qty
                    self.side = fill.side
                    self.qty = remainder
                    self.avg_price = fill.price
        self.fees_paid += fill.fee


@dataclass(slots=True)
class Account:
    balance: float
    position: Position = field(default_factory=Position)

