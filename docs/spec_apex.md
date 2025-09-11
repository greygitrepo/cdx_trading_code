# APEX Strategy Spec (Overview)

Purpose
- Regime-switching scalper composed of two plays:
  - Regime A (VWAP reversion): passive PostOnly entries near best price with TTL
  - Regime B (Momentum breakout): taker/IOC entries with slip guard

Configuration
- YAML source: `params.apex.*` in `bot/configs/config.yaml`
  - `scanner`: universe scanning thresholds (turnover, spread, depth)
  - `regime`: regime thresholds (ADX, volatility spike multiple)
  - `strategy_A`: VWAP reversion knobs (RSI2/bollinger/vwap deviation, TP/SL/trailing/TTL)
  - `strategy_B`: momentum knobs (EMA cross, above VWAP, TP/SL/trailing, slip guard)

Runtime Wiring
- LiveTestnetRunner (`bot/app/runners/live_testnet_runner.py`):
  1) Scanner/regime context is approximated from live snapshot (conservative defaults)
  2) `decide_apex(context, cfg)` returns a dictionary signal or None
  3) `apex_executor.build_entry_from_signal(...)` converts to an execution plan (Limit/Market, TIF, TTL)
  4) Plan is adapted to the existing order placement path and recorded in the trade ledger
  5) Generic post-entry management (partials/trailing/time stop) is applied

Actor Mode
- A minimal APEX event hook is added in `bot/actors/symbol_actor.py` to accept a single event:
  - Event shape: `{ "type": "apex_signal", "payload": { "side": "BUY|SELL" } }`
  - The actor issues one order via the `OrderRouter`

Notes
- The runner intentionally keeps indicator requirements light for testability; regime/entry gates default to non-triggering values unless provided by a richer data source.
- TP/SL attachment on create follows the global runtime policy; APEX per-play TP/SL fields can be mapped further as needed.

Usage
```
python bot/scripts/run_live_testnet.py --profile quick-test --strategy apex
```

