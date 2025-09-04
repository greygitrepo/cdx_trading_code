"""SQLite persistence for trades/logs (minimal skeleton)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty REAL NOT NULL,
  price REAL NOT NULL,
  fee REAL NOT NULL,
  is_maker INTEGER NOT NULL
);
"""


@dataclass
class SQLiteStore:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.path)) as conn:
            conn.execute(SCHEMA)
            conn.commit()

    def log_trade(
        self,
        ts: int,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        fee: float,
        is_maker: bool,
    ) -> None:
        with sqlite3.connect(str(self.path)) as conn:
            conn.execute(
                "INSERT INTO trades (ts, symbol, side, qty, price, fee, is_maker) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, symbol, side, qty, price, fee, 1 if is_maker else 0),
            )
            conn.commit()
