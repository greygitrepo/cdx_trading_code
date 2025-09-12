from dataclasses import dataclass


@dataclass
class TradeRecord:
    side: str
    entry: float
    pnl: float
