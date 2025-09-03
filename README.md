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

## Configuration
- Default app config: `bot/configs/config.yaml`
- Parameter pack: `bot/configs/params_gumiho.yaml`
You can load/validate them via `bot.configs.schemas.load_app_config` and `load_params`.
