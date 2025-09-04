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
- Pulls L1 orderbook and computes mid price
- Builds a tiny order plan from a dummy long signal, runs risk checks
- Places a small order and immediately cancels it (or `DRY_RUN=true` to simulate)

Safety and notes
- Secrets: only read from environment; do not commit `.env`.
- Rate limit: built-in exponential backoff on 429/selected `retCode`s with retries.
- Resilience: idempotency via `orderLinkId` on order placement.
- Logging: structured JSONL events under `logs/live_testnet/events.jsonl` and a rotating `app.log`.

## Data Layer (Stub/Live)
- Modes via env: `STUB_MODE` (default true), `PAPER_MODE` (default true), `LIVE_MODE` (default false).
- WS (stub replay): `bot/core/data_ws.py` reads `data/stubs/ws/*.jsonl` for ticker/orderbook (L1/L5).
- REST (stub fixtures): `bot/core/data_rest.py` reads `data/stubs/rest/*.json` when `STUB_MODE=true`.
- Switch to live by exporting `STUB_MODE=false` (WS live wiring not enabled in CI).

## Configuration
- Default app config: `bot/configs/config.yaml`
- Parameter pack: `bot/configs/params_gumiho.yaml`
You can load/validate them via `bot.configs.schemas.load_app_config` and `load_params`.
