from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Literal

Liquidity = Literal["maker", "taker"]
ExitReason = Literal["TP", "SL", "TRAIL", "TIME_STOP", "MANUAL", "ERROR"]


@dataclass
class TradeLedgerRow:
    # identity
    trade_id: str                 # e.g., "{run_id}:{symbol}:{entry_time_ms}"
    run_id: str
    symbol: str
    side: Literal["LONG", "SHORT"]

    # entry
    entry_time: int               # epoch ms
    entry_price: float
    entry_qty: float
    entry_value_usdt: float
    entry_liquidity: Optional[Liquidity]
    entry_fee_usdt: float
    entry_slippage_pct: float

    # exit
    exit_time: int                # epoch ms
    exit_price: float
    exit_qty: float
    exit_value_usdt: float
    exit_liquidity: Optional[Liquidity]
    exit_fee_usdt: float
    exit_slippage_pct: float
    exit_reason: ExitReason

    # derived
    hold_secs: float
    realized_pnl_usdt: float      # fees included
    realized_pnl_pct_on_value: float

    # excursions (relative to entry_price, + = favorable for side)
    max_favorable_excursion_pct: float
    max_adverse_excursion_pct: float

    # order quality
    orders_submitted: int
    orders_filled: int
    orders_canceled: int

    # entry-time market context
    spread_pct_at_entry: float
    depth_L5_bid_usd: float
    depth_L5_ask_usd: float
    imbalance_L5: float           # (bidUSD - askUSD) / (bidUSD + askUSD)
    tps_entry: float              # ticks per second
    volatility_1m_pct: float
    volatility_5m_pct: float
    funding_min_to_next: Optional[float]

    # trailing (optional)
    trail_armed_at_price: Optional[float]
    trail_steps: Optional[int]
    max_trail_offset_pct: Optional[float]

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def csv_header_order():
        return [
            "trade_id","run_id","symbol","side",
            "entry_time","entry_price","entry_qty","entry_value_usdt",
            "entry_liquidity","entry_fee_usdt","entry_slippage_pct",
            "exit_time","exit_price","exit_qty","exit_value_usdt",
            "exit_liquidity","exit_fee_usdt","exit_slippage_pct","exit_reason",
            "hold_secs","realized_pnl_usdt","realized_pnl_pct_on_value",
            "max_favorable_excursion_pct","max_adverse_excursion_pct",
            "orders_submitted","orders_filled","orders_canceled",
            "spread_pct_at_entry","depth_L5_bid_usd","depth_L5_ask_usd","imbalance_L5",
            "tps_entry","volatility_1m_pct","volatility_5m_pct","funding_min_to_next",
            "trail_armed_at_price","trail_steps","max_trail_offset_pct"
        ]

