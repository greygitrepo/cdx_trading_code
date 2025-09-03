"""REST wrapper tests using httpx.MockTransport (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from bot.core.api import BybitREST


def _mock_client_factory(payload_map: dict[str, Any]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        path = request.url.path
        data = payload_map.get(path, {})
        return httpx.Response(200, content=json.dumps(data))

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="https://api.test", timeout=1.0)


def test_server_time_and_tickers_wrapper() -> None:
    payloads = {
        "/v5/market/time": {"time": 1234567890},
        "/v5/market/tickers": {"result": {"list": [{"symbol": "BTCUSDT"}]}}
    }
    rest = BybitREST(base_url="https://api.test", client_factory=lambda base, to: _mock_client_factory(payloads))
    assert rest.server_time() == 1234567890
    data = rest.tickers(category="linear")
    assert data["result"]["list"][0]["symbol"] == "BTCUSDT"

