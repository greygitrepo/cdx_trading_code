"""Thin wrapper client for Bybit TESTNET used by integration tests.

Relies on env: TESTNET=true, LIVE_MODE=true, BYBIT_API_KEY/SECRET
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bot.core.exchange.bybit_v5 import BybitV5Client, BybitAPIError


class BybitClientTestnet:
    def __init__(self) -> None:
        # Ensure default category linear
        self.client = BybitV5Client(testnet=True, category="linear")

    # -------- Market data --------
    def get_mark_price(self, symbol: str) -> float:
        # Use best effort: ticker last price if available; fallback mid from level-1 book
        try:
            tk = self.client.get_tickers(symbol=symbol)
            lst = tk.get("result", {}).get("list", [])
            if lst:
                p = float(lst[0].get("lastPrice") or lst[0].get("lastPriceE8") or 0)
                if p > 0:
                    return p
        except Exception:
            pass
        ob = self.client.get_orderbook(symbol)
        try:
            bids = ob.get("result", {}).get("b", [[0]])
            asks = ob.get("result", {}).get("a", [[0]])
            b = float(bids[0][0]) if bids else 0.0
            a = float(asks[0][0]) if asks else 0.0
            if b > 0 and a > 0:
                return (a + b) / 2.0
        except Exception:
            pass
        return 0.0

    def get_market_rules(self, symbol: str) -> Any:
        ins = self.client.get_instruments(category=self.client.default_category)
        flt = self.client.extract_symbol_filters(ins, symbol)
        return type(
            "Rule",
            (),
            {
                "lot_step": flt.get("qtyStep"),
                "tick_size": flt.get("tickSize"),
                "min_qty": flt.get("minOrderQty"),
            },
        )()

    def get_klines(
        self, symbol: str, interval: str = "1", limit: int = 10
    ) -> List[Dict[str, Any]]:
        # Use private request helper
        params = {
            "category": self.client.default_category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        j = self.client._request("GET", "/v5/market/kline", params=params, auth=False)  # noqa: SLF001
        return j.get("result", {}).get("list", [])

    # -------- Portfolio state --------
    def position_symbols(self) -> List[str]:
        try:
            pos = self.client.get_positions(settleCoin="USDT")
            out = []
            for it in pos.get("result", {}).get("list", []):
                try:
                    if float(it.get("size") or 0) != 0:
                        out.append(it.get("symbol"))
                except Exception:
                    continue
            return out
        except BybitAPIError:
            return []

    def open_order_symbols(self) -> List[str]:
        try:
            oo = self.client.get_open_orders()
            syms = set()
            for it in oo.get("result", {}).get("list", []):
                if it.get("symbol"):
                    syms.add(it.get("symbol"))
            return list(syms)
        except BybitAPIError:
            return []

    # -------- Trading helpers --------
    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> str:
        tif = "IOC" if price is None else "GTC"
        res = self.client.place_order(
            symbol=symbol,
            side=side.upper(),
            qty=str(qty),
            orderType=("Market" if price is None else "Limit"),
            timeInForce=tif,
            price=(str(price) if price is not None else None),
            reduceOnly=reduce_only,
        )
        return res.get("result", {}).get("orderId", "")

    def close_position(self, symbol: str) -> None:
        # Fetch current size then send reduce-only order
        pos = self.client.get_positions(symbol=symbol)
        lst = pos.get("result", {}).get("list", [])
        if not lst:
            return
        p = lst[0]
        size = abs(float(p.get("size") or 0))
        if size <= 0:
            return
        side = "SELL" if p.get("side") == "Buy" else "BUY"
        self.client.close_position_market(symbol=symbol, side=side, qty=str(size))

    def get_position_size(self, symbol: str) -> float:
        try:
            pos = self.client.get_positions(symbol=symbol)
            lst = pos.get("result", {}).get("list", [])
            if not lst:
                return 0.0
            return float(lst[0].get("size") or 0)
        except Exception:
            return 0.0
