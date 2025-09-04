from __future__ import annotations

import hashlib
import hmac
import json

from bot.core.exchange.bybit_v5 import BybitV5Client


def test_signing_prehash_and_signature_matches_snapshot(monkeypatch):
    client = BybitV5Client(api_key="test_key", api_secret="secret", testnet=True)
    # Freeze recv_window
    monkeypatch.setattr(client, "recv_window_ms", 5000)
    # Deterministic timestamp
    ts = 1700000000000

    # Example POST body
    body = {
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "orderType": "Limit",
        "qty": "0.01",
        "timeInForce": "GTC",
        "price": "25000",
        "orderLinkId": "abc123",
        "reduceOnly": None,
    }
    payload = client._minified_json(body)
    prehash = client._build_prehash(str(ts), client.api_key, str(client.recv_window_ms), payload)
    # Snapshot of expected prehash string
    assert prehash == (
        "1700000000000" "test_key" "5000"
        + json.dumps({
            "category": "linear",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "orderType": "Limit",
            "qty": "0.01",
            "timeInForce": "GTC",
            "price": "25000",
            "orderLinkId": "abc123",
        }, separators=(",", ":"))
    )

    # Expected signature computed independently
    expected_sig = hmac.new(
        b"secret", prehash.encode(), hashlib.sha256
    ).hexdigest()
    got_sig = client._sign(ts, payload)
    assert got_sig == expected_sig


def test_place_order_payload(monkeypatch):
    client = BybitV5Client(api_key="k", api_secret="s", testnet=True)
    sent = {}

    def _fake_request(method, path, params=None, data=None, auth=False, max_retries=3):  # noqa: D401
        sent.update({
            "method": method,
            "path": path,
            "params": params,
            "data": data,
            "auth": auth,
        })
        return {"retCode": 0, "retMsg": "OK", "result": {}}

    monkeypatch.setattr(client, "_request", _fake_request)
    client.place_order(
        symbol="BTCUSDT",
        side="BUY",
        qty="0.005",
        price="30000",
        orderType="Limit",
        timeInForce="GTC",
        orderLinkId="link1",
    )
    assert sent["method"] == "POST"
    assert sent["path"] == "/v5/order/create"
    assert sent["auth"] is True
    assert sent["data"]["symbol"] == "BTCUSDT"
    assert sent["data"]["orderType"] == "Limit"
    assert sent["data"]["timeInForce"] == "GTC"
    assert sent["data"]["price"] == "30000"
    assert sent["data"]["orderLinkId"] == "link1"


def test_positions_requires_symbol_or_settlecoin():
    client = BybitV5Client(api_key="k", api_secret="s", testnet=True)
    try:
        client.get_positions()
        assert False, "Expected ValueError when missing symbol/settleCoin"
    except ValueError:
        pass


def test_get_instruments_alias(monkeypatch):
    client = BybitV5Client(api_key="k", api_secret="s", testnet=True)
    seen = {}

    def _fake_request(method, path, params=None, data=None, auth=False, max_retries=3):
        seen.update({"method": method, "path": path, "params": params, "auth": auth})
        return {"retCode": 0, "retMsg": "OK", "result": {"list": []}}

    monkeypatch.setattr(client, "_request", _fake_request)
    client.get_instruments(category="linear")
    assert seen["method"] == "GET"
    assert seen["path"] == "/v5/market/instruments-info"
    assert seen["params"]["category"] == "linear"
    assert seen["auth"] is False


def test_set_leverage_payload(monkeypatch):
    client = BybitV5Client(api_key="k", api_secret="s", testnet=True)
    sent = {}

    def _fake_request(method, path, params=None, data=None, auth=False, max_retries=3):
        sent.update({"method": method, "path": path, "data": data, "auth": auth})
        return {"retCode": 0, "retMsg": "OK", "result": {}}

    monkeypatch.setattr(client, "_request", _fake_request)
    client.set_leverage(symbol="BTCUSDT", buyLeverage=10, sellLeverage=10, category="linear")
    assert sent["method"] == "POST"
    assert sent["path"] == "/v5/position/set-leverage"
    assert sent["auth"] is True
    assert sent["data"]["symbol"] == "BTCUSDT"
    assert sent["data"]["buyLeverage"] == "10"
    assert sent["data"]["sellLeverage"] == "10"


def test_set_trading_stop_payload(monkeypatch):
    client = BybitV5Client(api_key="k", api_secret="s", testnet=True)
    sent = {}

    def _fake_request(method, path, params=None, data=None, auth=False, max_retries=3):
        sent.update({"method": method, "path": path, "data": data, "auth": auth})
        return {"retCode": 0, "retMsg": "OK", "result": {}}

    monkeypatch.setattr(client, "_request", _fake_request)
    client.set_trading_stop(symbol="BTCUSDT", takeProfit=30050, stopLoss=29950, trailingStop=30, category="linear")
    assert sent["method"] == "POST"
    assert sent["path"] == "/v5/position/trading-stop"
    assert sent["auth"] is True
    assert sent["data"]["symbol"] == "BTCUSDT"
    assert sent["data"]["takeProfit"] == "30050"
    assert sent["data"]["stopLoss"] == "29950"
    assert sent["data"]["trailingStop"] == "30"


def test_close_position_market_payload(monkeypatch):
    client = BybitV5Client(api_key="k", api_secret="s", testnet=True)
    sent = {}

    def _fake_request(method, path, params=None, data=None, auth=False, max_retries=3):
        sent.update({"method": method, "path": path, "data": data, "auth": auth})
        return {"retCode": 0, "retMsg": "OK", "result": {}}

    monkeypatch.setattr(client, "_request", _fake_request)
    client.close_position_market(symbol="BTCUSDT", side="SELL", qty="0.01", category="linear")
    assert sent["method"] == "POST"
    assert sent["path"] == "/v5/order/create"
    assert sent["auth"] is True
    assert sent["data"]["reduceOnly"] is True
    assert sent["data"]["orderType"] == "Market"
