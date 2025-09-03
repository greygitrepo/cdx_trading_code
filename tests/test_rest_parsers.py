"""REST parsers on STUB fixtures without network."""

from __future__ import annotations

from bot.core.data_rest import REST


def test_instruments_and_tickers_stub() -> None:
    api = REST()
    ins = api.instruments()
    assert ins["result"]["list"][0]["symbol"] == "BTCUSDT"
    t = api.tickers(category="linear")
    assert t["result"]["list"][0]["symbol"] == "BTCUSDT"


def test_funding_oi_and_time_stub() -> None:
    api = REST()
    f = api.funding()
    oi = api.open_interest()
    tm = api.server_time()
    assert int(f["result"]["list"][0]["fundingRateTimestamp"]) > 0
    assert int(oi["result"]["list"][0]["timestamp"]) > 0
    assert int(tm["time"]) > 0

