# cdx_trading_code

Bybit v5 1-minute scalping system scaffold. This repository follows the execution policy defined in `docs/spec.md` and evolves through Phase 1–4 with tests and CI green (no secrets required).

## Project structure
- `bot/core`: core modules (types, fees/slippage, backtester, etc.)
- `bot/configs`: config and parameter schemas (Pydantic) + YAML
- `bot/scripts`: runnable scripts (paper/live/report)
- `tests`: unit tests (fees/slippage/partial fills)
- `docs/spec.md`: single source of truth spec

## Quickstart
1) Install dependencies
```bash
pip install -r requirements.txt
```

2) Lint & Test
```bash
ruff check .
pytest -q
```

3) Generate paper report
```bash
python bot/scripts/run_paper.py
```
Report is written to `reports/paper.html`.

## Quickstart (Live Testnet)
- Install deps and prepare an `.env` from `.env.sample` with your Bybit testnet API keys (never commit secrets).
- Ensure env toggles:
  - `STUB_MODE=false`, `PAPER_MODE=false`, `LIVE_MODE=true`, `TESTNET=true`
  - `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `BYBIT_SYMBOL=BTCUSDT`

Steps
```bash
pip install -r requirements.txt

# export envs (or use a .env loader in your shell)
export STUB_MODE=false PAPER_MODE=false LIVE_MODE=true TESTNET=true
export BYBIT_API_KEY=xxx BYBIT_API_SECRET=yyy BYBIT_SYMBOL=BTCUSDT

python bot/scripts/run_live_testnet.py
```

What it does
- Validates API key via `/v5/account/wallet-balance` and logs result
- Loads instrument filters (tickSize/qtyStep/minQty) and sets leverage
- Starts a timed loop: regime checks → strategy scoring(MIS/VRS/LSR) → order routing (maker/taker) → reflect (orders/positions) → cancel (smoke)
- Rotates across symbols when no strategy consensus after `CONSENSUS_TICKS` (see Universe & Rotation envs). Press `EXIT_KEY` (default `q`) to stop.
- Applies precision-aware sizing, funding-window avoidance, trailing/TP/SL, and time-stop

Safety and notes
- Secrets: only read from environment; do not commit `.env`.
- Rate limit: built-in exponential backoff on 429/selected `retCode`s with retries.
- Resilience: idempotency via `orderLinkId` on order placement.
- Logging: structured JSONL events under `logs/run_*/events.jsonl` and a rotating `app.log`.
- Optional WS: set `ENABLE_PRIVATE_WS=true` and install `websocket-client` to stream private `order/execution/position` events into JSONL.

Env highlights
- `LEVERAGE`, `MAX_ALLOC_PCT`, `MIN_FREE_BALANCE_USDT`, `SLIPPAGE_GUARD_PCT`, `DRY_RUN`
- Regime/signal: `MIS_SPREAD_THRESHOLD`, `SPREAD_PAUSE_MULT`, `MIN_DEPTH_USD`
- Funding guard: `AVOID_TAKER_WITHIN_MIN`
- Protection: `TP_PCT`, `SL_PCT`, `TRAIL_AFTER_TP1_PCT`, `TIME_STOP_SEC`

## Data Layer (Stub/Live)
- Modes via env: `STUB_MODE` (default true), `PAPER_MODE` (default true), `LIVE_MODE` (default false).
- WS (stub replay): `bot/core/data_ws.py` reads `data/stubs/ws/*.jsonl` for ticker/orderbook (L1/L5).
- REST (stub fixtures): `bot/core/data_rest.py` reads `data/stubs/rest/*.json` when `STUB_MODE=true`.
- Switch to live by exporting `STUB_MODE=false` (WS live wiring not enabled in CI).

## Configuration
- Default app config: `bot/configs/config.yaml`
- Parameter pack: `bot/configs/params_gumiho.yaml`
You can load/validate them via `bot.configs.schemas.load_app_config` and `load_params`.
- Universe/Rotation: `SYMBOL_UNIVERSE`, `DISCOVER_SYMBOLS`, `UNIVERSE_TOP_N`, `CONSENSUS_TICKS`, `NO_TRADE_SLEEP_SEC`, `LOOP_IDLE_SEC`, `EXIT_KEY`, `ORDER_SIZE_USDT`

### Quick-Test Profile (fast testnet fills)

To quickly validate live wiring and generate reports with several fills on testnet:

1) Run with the quick-test profile

```
python bot/scripts/run_live_testnet.py --profile quick-test
```

This applies relaxed filters and taker-friendly routing:
- maker_post_only=false, taker_on_strong_score=true, fallback_ioc=true
- MIN_DEPTH_USD≈2000, SLIPPAGE_GUARD_PCT≈0.0015, CONSENSUS_TICKS≈2
- More frequent signals: keltner_mult≈1.25, rsi2_low≈8, rsi2_high≈92, htf_bias.disabled
- RR: TP≈0.10%, SL≈0.12%, TIME_STOP≈8m

2) Generate a report

```
python bot/scripts/make_report.py --run_id <run_id>
```

The HTML report is saved to `reports/quick_test_<run_id>.html` with fill rate, slippage estimate, and basic summaries.

Note: Before real trading, revert to conservative settings or omit `--profile quick-test`.
