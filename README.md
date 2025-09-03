# cdx_trading_code

Scaffolding for a Bybit 1-minute scalping system.

## Project structure
- `bot/`: core modules and scripts
- `tests/`: unit tests
- `docs/spec.md`: detailed specification

## Installation
```bash
pip install -r requirements.txt
```

## Usage
Generate a dummy paper trading report:
```bash
python bot/scripts/run_paper.py
```
The HTML report will be written to `reports/paper.html`.

## Testing
```bash
ruff check .
pytest -q
```
