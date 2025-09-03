"""Minimal REST wrapper for Bybit v5 public endpoints (offline-testable).

Provides simple sync client using httpx.Client with retry and timeout. Tests
use httpx.MockTransport to avoid network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx


@dataclass
class BybitREST:
    base_url: str
    timeout: float = 5.0
    retries: int = 2
    client_factory: Callable[[str, float], httpx.Client] | None = None

    def _client(self) -> httpx.Client:
        if self.client_factory is not None:
            return self.client_factory(self.base_url, self.timeout)
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict:
        last_exc: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                with self._client() as client:
                    resp = client.get(path, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    return data
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    # Public endpoints (minimal schema)
    def server_time(self) -> int:
        data = self._get("/v5/market/time")
        # Accept either direct int or wrapped
        if isinstance(data, dict) and "time" in data:
            return int(data["time"])  # type: ignore[return-value]
        if isinstance(data, int):
            return int(data)
        raise ValueError("unexpected response for server_time")

    def instruments(self, category: str = "linear") -> dict:
        return self._get("/v5/market/instruments-info", {"category": category})

    def tickers(self, category: str = "linear", symbol: str | None = None) -> dict:
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return self._get("/v5/market/tickers", params)

    def funding_history(self, category: str = "linear", symbol: str | None = None) -> dict:
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return self._get("/v5/market/funding/history", params)

    def open_interest(self, category: str = "linear", symbol: str | None = None) -> dict:
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return self._get("/v5/market/open-interest", params)

