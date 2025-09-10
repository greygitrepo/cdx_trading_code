from __future__ import annotations

from pathlib import Path
import csv

from bot.core.reporting.ledger import TradeLedgerRow
from bot.core.reporting.writer import TradeLedgerWriter
from bot.core.ledger import TradeLedger


def test_csv_header_order_stable() -> None:
    expected = [
        "trade_id","run_id","symbol","side",
        "entry_time","entry_price","entry_qty","entry_value_usdt",
        "entry_liquidity","entry_fee_usdt","entry_slippage_pct",
        "exit_time","exit_price","exit_qty","exit_value_usdt",
        "exit_liquidity","exit_fee_usdt","exit_slippage_pct","exit_reason",
        "hold_secs","realized_pnl_usdt","realized_pnl_pct_on_value",
        "max_favorable_excursion_pct","max_adverse_excursion_pct",
        "orders_submitted","orders_filled","orders_canceled",
        "spread_pct_at_entry","depth_L5_bid_usd","depth_L5_ask_usd","imbalance_L5",
        "tps_entry","volatility_1m_pct","volatility_5m_pct","funding_min_to_next",
        "trail_armed_at_price","trail_steps","max_trail_offset_pct",
    ]
    assert TradeLedgerRow.csv_header_order() == expected


def test_writer_creates_both_formats(tmp_path: Path) -> None:
    run_id = "run_TEST"
    base_dir = tmp_path / run_id
    w = TradeLedgerWriter(run_id, str(base_dir))
    row = TradeLedgerRow(
        trade_id=f"{run_id}:BTCUSDT:1",
        run_id=run_id,
        symbol="BTCUSDT",
        side="LONG",
        entry_time=1,
        entry_price=100.0,
        entry_qty=0.01,
        entry_value_usdt=1.0,
        entry_liquidity="taker",
        entry_fee_usdt=0.001,
        entry_slippage_pct=0.01,
        exit_time=2,
        exit_price=101.0,
        exit_qty=0.01,
        exit_value_usdt=1.01,
        exit_liquidity="taker",
        exit_fee_usdt=0.001,
        exit_slippage_pct=0.01,
        exit_reason="TP",
        hold_secs=1.0,
        realized_pnl_usdt=0.008,
        realized_pnl_pct_on_value=0.8,
        max_favorable_excursion_pct=1.2,
        max_adverse_excursion_pct=-0.4,
        orders_submitted=2,
        orders_filled=1,
        orders_canceled=1,
        spread_pct_at_entry=0.02,
        depth_L5_bid_usd=50000.0,
        depth_L5_ask_usd=52000.0,
        imbalance_L5=0.1,
        tps_entry=12.0,
        volatility_1m_pct=0.3,
        volatility_5m_pct=0.5,
        funding_min_to_next=None,
        trail_armed_at_price=None,
        trail_steps=None,
        max_trail_offset_pct=None,
    )
    w.append(row, formats=("csv", "jsonl"))
    csv_fp = base_dir / "trades.csv"
    jsonl_fp = base_dir / "trades.jsonl"
    assert csv_fp.exists() and jsonl_fp.exists()
    # CSV header + 1 data row
    with csv_fp.open() as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2
    assert rows[0] == TradeLedgerRow.csv_header_order()


def test_mfe_mae_sign_correctness(tmp_path: Path) -> None:
    # Use existing TradeLedger lifecycle helpers
    ld = TradeLedger(run_id="run_TEST", out_dir=tmp_path)
    # LONG trade entry at 100
    rec = ld.on_entry(symbol="BTCUSDT", side_long=True, entry_ts=1, price=100.0, qty=1.0)
    # price moves to 103 (MFE +3%), then down to 98 (MAE -2%)
    ld.update_mfe_mae("BTCUSDT", now_price=103.0)
    ld.update_mfe_mae("BTCUSDT", now_price=98.0)
    assert rec.max_favorable_excursion_pct >= 0
    assert rec.max_adverse_excursion_pct <= 0
    # Close
    ld.on_exit(symbol="BTCUSDT", exit_ts=2, price=101.0, qty=1.0, reason="TP", realized_pnl_usdt=1.0)

    # SHORT trade entry at 100
    rec2 = ld.on_entry(symbol="ETHUSDT", side_long=False, entry_ts=1, price=100.0, qty=1.0)
    # price down to 95 (MFE +5%), then up to 102 (MAE -2%) in short convention
    ld.update_mfe_mae("ETHUSDT", now_price=95.0)
    ld.update_mfe_mae("ETHUSDT", now_price=102.0)
    assert rec2.max_favorable_excursion_pct >= 0
    assert rec2.max_adverse_excursion_pct <= 0
    ld.on_exit(symbol="ETHUSDT", exit_ts=2, price=99.0, qty=1.0, reason="TP", realized_pnl_usdt=1.0)

