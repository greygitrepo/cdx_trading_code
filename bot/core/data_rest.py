"""REST layer with STUB mode and httpx fallback.

In STUB_MODE, reads JSON from data/stubs/rest/*.json and returns dicts.
In non-stub mode, uses httpx to call Bybit v5 public endpoints with retry/timeout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from .config import get_modes


STUB_DIR = Path("data/stubs/rest")


def _read_stub(name: str) -> dict:
    path = STUB_DIR / f"{name}.json"
    return json.loads(path.read_text())


class REST:
    def __init__(
        self,
        base_url: str = "https://api.bybit.com",
        timeout: float = 5.0,
        retries: int = 2,
        client_factory: Callable[[str, float], httpx.Client] | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.client_factory = client_factory

    def _client(self) -> httpx.Client:
        if self.client_factory is not None:
            return self.client_factory(self.base_url, self.timeout)
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict:
        modes = get_modes()
        if modes.stub:
            # Map path to stub name
            name = {
                "/v5/market/instruments-info": "instruments",
                "/v5/market/tickers": "tickers",
                "/v5/market/funding/history": "funding",
                "/v5/market/open-interest": "open_interest",
                "/v5/market/time": "time",
            }[path]
            return _read_stub(name)

        last_exc: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                with self._client() as client:
                    resp = client.get(path, params=params)
                    resp.raise_for_status()
                    return resp.json()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    # Public
    def instruments(self, category: str = "linear") -> dict:
        return self._get("/v5/market/instruments-info", {"category": category})

    def tickers(self, category: str = "linear", symbol: str | None = None) -> dict:
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return self._get("/v5/market/tickers", params)

    def funding(self, category: str = "linear", symbol: str | None = None) -> dict:
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return self._get("/v5/market/funding/history", params)

    def open_interest(
        self, category: str = "linear", symbol: str | None = None
    ) -> dict:
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return self._get("/v5/market/open-interest", params)

    def server_time(self) -> dict:
        return self._get("/v5/market/time", None)
