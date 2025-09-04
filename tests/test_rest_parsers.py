"""REST parsers on STUB fixtures without network."""

from __future__ import annotations

import pytest

from bot.core.data_rest import REST


@pytest.mark.unit
def test_instruments_and_tickers_stub(monkeypatch) -> None:
    # Force stub mode even when integration env is present
    monkeypatch.setenv("STUB_MODE", "true")
    monkeypatch.setenv("LIVE_MODE", "false")
    monkeypatch.setenv("TESTNET", "false")
    api = REST()
    ins = api.instruments()
    assert ins["result"]["list"][0]["symbol"] == "BTCUSDT"
    t = api.tickers(category="linear")
    assert t["result"]["list"][0]["symbol"] == "BTCUSDT"

@pytest.mark.unit
def test_funding_oi_and_time_stub(monkeypatch) -> None:
    # Force stub mode
    monkeypatch.setenv("STUB_MODE", "true")
    monkeypatch.setenv("LIVE_MODE", "false")
    monkeypatch.setenv("TESTNET", "false")
    api = REST()
    f = api.funding()
    oi = api.open_interest()
    tm = api.server_time()
    assert int(f["result"]["list"][0]["fundingRateTimestamp"]) > 0
    assert int(oi["result"]["list"][0]["timestamp"]) > 0
    assert int(tm["time"]) > 0
