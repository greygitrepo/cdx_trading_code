from __future__ import annotations

import os
import signal
import sys
from dataclasses import dataclass
from typing import List

from .exchange.bybit_v5 import BybitV5Client


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.lower() == "true"


@dataclass
class Universe:
    symbols: List[str]
    discovered: bool


def build_universe(client: BybitV5Client) -> Universe:
    # 1) Static list if provided
    raw = _env_str("SYMBOL_UNIVERSE", "").strip()
    if raw:
        syms = [s.strip() for s in raw.split(",") if s.strip()]
        return Universe(symbols=syms, discovered=False)

    # 2) Discovery if enabled
    if _env_bool("DISCOVER_SYMBOLS", True):
        cat = _env_str("CATEGORY", _env_str("BYBIT_CATEGORY", "linear"))
        topn = _env_int("UNIVERSE_TOP_N", 10)
        try:
            # instruments-info for trading symbols
            ins = client.get_instruments(category=cat)
            tradable = {it.get("symbol") for it in ins.get("result", {}).get("list", []) if it.get("status") == "Trading"}
        except Exception:
            tradable = set()
        try:
            # tickers for 24h volume/turnover ranking
            tks = client.get_tickers(category=cat)
            items = tks.get("result", {}).get("list", [])
            # Filter USDT symbols and sort by turnover24h desc
            filtered = [it for it in items if str(it.get("symbol", "")).endswith("USDT")]
            for it in filtered:
                # normalize numeric fields
                for k in ("turnover24h", "volume24h"):
                    try:
                        it[k] = float(it.get(k) or 0)
                    except Exception:
                        it[k] = 0.0
            filtered.sort(key=lambda x: (x.get("turnover24h", 0), x.get("volume24h", 0)), reverse=True)
            syms_ranked = [it.get("symbol") for it in filtered if it.get("symbol")]
        except Exception:
            syms_ranked = []
        # intersect with tradable if available
        syms = [s for s in syms_ranked if (not tradable or s in tradable)][:topn]
        if syms:
            return Universe(symbols=syms, discovered=True)
    # 3) Fallback sensible defaults
    return Universe(symbols=[_env_str("BYBIT_SYMBOL", "BTCUSDT")], discovered=False)


class ExitFlag:
    def __init__(self) -> None:
        self._stop = False
        self._exit_key = _env_str("EXIT_KEY", "q")
        try:
            signal.signal(signal.SIGINT, self._handle)
            signal.signal(signal.SIGTERM, self._handle)
        except Exception:
            pass

    def _handle(self, signum, frame) -> None:  # noqa: ANN001
        self._stop = True

    def check(self) -> bool:
        if self._stop:
            return True
        # non-blocking key check on stdin
        try:
            # Only attempt when stdin is a TTY
            if sys.stdin and sys.stdin.isatty():
                import select

                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    ch = sys.stdin.read(1)
                    if ch and ch.strip().lower() == self._exit_key.lower():
                        self._stop = True
        except Exception:
            pass
        return self._stop
