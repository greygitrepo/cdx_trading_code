"""Bybit v5 REST client (testnet/mainnet) with HMAC auth and retries.

This client implements a minimal subset required for live testnet smoke:
- get_symbols
- get_orderbook
- place_order
- cancel_order
- get_open_orders
- get_positions
- get_wallet_balance

Env vars used (with reasonable defaults for testnet):
- BYBIT_API_KEY, BYBIT_API_SECRET
- TESTNET=true|false (default true)
- BYBIT_CATEGORY=linear (linear|inverse|spot)

Notes:
- Signing follows v5 spec: sign = HMAC_SHA256(secret, ts + apiKey + recvWindow + payload)
- payload is querystring for GET/DELETE, or minified JSON string for POST
- Headers: X-BAPI-API-KEY, X-BAPI-SIGN, X-BAPI-TIMESTAMP, X-BAPI-RECV-WINDOW, Content-Type
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

import httpx


DEFAULT_BASE_MAINNET = "https://api.bybit.com"
DEFAULT_BASE_TESTNET = "https://api-testnet.bybit.com"


class BybitAPIError(Exception):
    def __init__(self, ret_code: int, ret_msg: str, data: Any | None = None):
        super().__init__(f"Bybit API error {ret_code}: {ret_msg}")
        self.ret_code = ret_code
        self.ret_msg = ret_msg
        self.data = data


class BybitV5Client:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        *,
        testnet: bool | None = None,
        base_url: Optional[str] = None,
        recv_window_ms: int = 5000,
        timeout: float = 10.0,
        category: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("BYBIT_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("BYBIT_API_SECRET", "")
        if not self.api_key or not self.api_secret:
            # Allow unauthenticated market endpoints, but warn on private usage
            pass
        if testnet is None:
            testnet = os.environ.get("TESTNET", "true").lower() == "true"
        self.base_url = base_url or (DEFAULT_BASE_TESTNET if testnet else DEFAULT_BASE_MAINNET)
        self.recv_window_ms = recv_window_ms
        self._client = httpx.Client(timeout=timeout)
        self.default_category = category or os.environ.get("BYBIT_CATEGORY", "linear")

    # -------- Signing helpers --------
    @staticmethod
    def _canonical_query(params: Dict[str, Any] | None) -> str:
        if not params:
            return ""
        # Exclude None values; Bybit expects keys sorted by ASCII
        items = [(k, v) for k, v in params.items() if v is not None]
        items.sort(key=lambda kv: kv[0])
        return "&".join(f"{k}={kv if isinstance((kv := v), str) else json.dumps(v, separators=(',', ':'))}" for k, v in items)

    @staticmethod
    def _minified_json(data: Dict[str, Any] | None) -> str:
        if not data:
            return ""
        # Remove None to avoid signing nulls inadvertently
        clean = {k: v for k, v in data.items() if v is not None}
        return json.dumps(clean, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _build_prehash(ts: str, api_key: str, recv_window: str, payload: str) -> str:
        return f"{ts}{api_key}{recv_window}{payload}"

    def _sign(self, ts_ms: int, payload: str) -> str:
        recv = str(self.recv_window_ms)
        prehash = self._build_prehash(str(ts_ms), self.api_key, recv, payload)
        sig = hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).hexdigest()
        return sig

    # -------- Core request --------
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
        auth: bool = False,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        ts_ms = int(time.time() * 1000)
        attempt = 0
        while True:
            payload_for_sign = ""
            if auth:
                if method.upper() in {"GET", "DELETE"}:
                    payload_for_sign = self._canonical_query(params)
                else:
                    payload_for_sign = self._minified_json(data)
                headers.update(
                    {
                        "X-BAPI-API-KEY": self.api_key,
                        "X-BAPI-TIMESTAMP": str(ts_ms),
                        "X-BAPI-RECV-WINDOW": str(self.recv_window_ms),
                        "X-BAPI-SIGN": self._sign(ts_ms, payload_for_sign),
                    }
                )

            try:
                resp = self._client.request(method, url, params=params, json=data, headers=headers)
            except httpx.RequestError:
                if attempt >= max_retries:
                    raise
                time.sleep(2 ** attempt)
                attempt += 1
                continue

            if resp.status_code == 429 and attempt < max_retries:
                time.sleep(2 ** attempt)
                attempt += 1
                continue

            j = resp.json()
            ret_code = j.get("retCode", 0)
            if ret_code != 0:
                # Retry on transient codes, else raise
                if attempt < max_retries and ret_code in {10006, 10016, 10018, 110001}:
                    time.sleep(2 ** attempt)
                    attempt += 1
                    continue
                raise BybitAPIError(ret_code, j.get("retMsg", "unknown"), j)
            return j

    # -------- Public market endpoints --------
    def get_symbols(self, category: Optional[str] = None) -> Dict[str, Any]:
        params = {"category": category or self.default_category}
        return self._request("GET", "/v5/market/instruments-info", params=params, auth=False)

    def get_orderbook(self, symbol: str, depth: int = 1, category: Optional[str] = None) -> Dict[str, Any]:
        params = {
            "category": category or self.default_category,
            "symbol": symbol,
            "limit": depth,
        }
        return self._request("GET", "/v5/market/orderbook", params=params, auth=False)

    # -------- Private trading/account endpoints --------
    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: str | float,
        price: str | float | None = None,
        orderType: str = "Market",
        timeInForce: str = "GTC",
        orderLinkId: Optional[str] = None,
        category: Optional[str] = None,
        reduceOnly: Optional[bool] = None,
        takeProfit: Optional[str | float] = None,
        stopLoss: Optional[str | float] = None,
        tpTriggerBy: Optional[str] = None,
        slTriggerBy: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "category": category or self.default_category,
            "symbol": symbol,
            "side": side,
            "orderType": orderType,
            "qty": str(qty),
            "timeInForce": timeInForce,
            "orderLinkId": orderLinkId,
            "price": str(price) if price is not None else None,
            "reduceOnly": reduceOnly,
            "takeProfit": str(takeProfit) if takeProfit is not None else None,
            "stopLoss": str(stopLoss) if stopLoss is not None else None,
            "tpTriggerBy": tpTriggerBy,
            "slTriggerBy": slTriggerBy,
        }
        return self._request("POST", "/v5/order/create", data=payload, auth=True)

    def cancel_order(
        self,
        *,
        symbol: str,
        orderId: Optional[str] = None,
        orderLinkId: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "category": category or self.default_category,
            "symbol": symbol,
            "orderId": orderId,
            "orderLinkId": orderLinkId,
        }
        return self._request("POST", "/v5/order/cancel", data=payload, auth=True)

    def get_open_orders(self, symbol: Optional[str] = None, *, category: Optional[str] = None) -> Dict[str, Any]:
        params = {
            "category": category or self.default_category,
            "symbol": symbol,
            "openOnly": 1,
        }
        return self._request("GET", "/v5/order/realtime", params=params, auth=True)

    def get_positions(
        self,
        *,
        category: Optional[str] = None,
        symbol: Optional[str] = None,
        settleCoin: Optional[str] = None,
    ) -> Dict[str, Any]:
        if symbol is None and settleCoin is None:
            raise ValueError("Bybit v5 requires either symbol or settleCoin for positions list")
        params = {
            "category": category or self.default_category,
            "symbol": symbol,
            "settleCoin": settleCoin,
        }
        return self._request("GET", "/v5/position/list", params=params, auth=True)

    def get_wallet_balance(self, *, accountType: str = "UNIFIED", coin: Optional[str] = None) -> Dict[str, Any]:
        params = {"accountType": accountType, "coin": coin}
        return self._request("GET", "/v5/account/wallet-balance", params=params, auth=True)

    # -------- Utilities --------
    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
