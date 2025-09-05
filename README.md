# OB-Flow v2: 호가창+거래량 기반 초단타 봇

이 레포는 v2(OB-Flow) 전용 경량 구조를 제공합니다. v1의 다전략 구조(MIS/VRS/LSR 등)를 제거하고, 호가창+거래량 기반 단일 전략만 유지합니다.

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

## Development

- Python 3.10/3.11
- Install deps: `pip install -r requirements.txt`
- Lint/format: `ruff format . && ruff check .`
- Run tests: `pytest -q -m "unit or strategy"`

### Pre-commit (recommended)

Install pre-commit to run Ruff automatically before commit:

```
pip install pre-commit
pre-commit install
```

Hooks run `ruff --fix` and `ruff format` on changed files.

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
- Parameter pack is under `params` in `config.yaml`. OB-Flow thresholds live under `params.obflow`.
You can load/validate via `bot.configs.schemas.load_app_config` and access `app.params`.
- Universe/Rotation: `SYMBOL_UNIVERSE`, `DISCOVER_SYMBOLS`, `UNIVERSE_TOP_N`, `CONSENSUS_TICKS`, `NO_TRADE_SLEEP_SEC`, `LOOP_IDLE_SEC`, `EXIT_KEY`, `ORDER_SIZE_USDT`

### OB-Flow thresholds (YAML)
`bot/core/signals/obflow.py` reads thresholds from YAML via `OBFlowConfig.from_params(app.params)`.
Tune under `bot/configs/config.yaml` → `params.obflow`:
- depth_imb_L5_min: imbalance threshold for Pattern A/C
- spread_tight_mult_mid: tight-spread multiplier for Pattern B
- tps_min_breakout: min ticks-per-second for breakout (placeholder)
- c_absorption_min: absorption strength threshold
- d_wide_spread_mult_mid: wide spread gate for Pattern D
- d_micro_dev_mult_spread: micro deviation vs spread for Pattern D

### Trade state helpers
`bot/core/execution/trade_state.py` provides partial TP, trailing after TP1, time-stop, and cooldown management for live/sim.

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

## Replay/Backtest (Stub LOB)
- OB-Flow 리플레이: `bot/scripts/run_replay_obflow.py`는 `data/stubs/ws/orderbook1_<SYMBOL>.jsonl`을 재생해 신호/부분청산/트레일/타임스탑/쿨다운 동작을 점검합니다.
```
python bot/scripts/run_replay_obflow.py --symbol BTCUSDT --max-sec 60 --qty-usdt 50
```
결과는 `logs/replay_obflow/<SYMBOL>.jsonl` 이벤트와 `reports/replay_obflow_<SYMBOL>.json` 요약으로 저장됩니다.
