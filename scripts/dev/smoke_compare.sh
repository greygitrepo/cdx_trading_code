#!/usr/bin/env bash
set -euo pipefail

# Smoke compare script: run replay twice and diff core fields.
# This is a placeholder to be integrated with a golden-run harness.

RUN_A="logs/run_a/events.jsonl"
RUN_B="logs/run_b/events.jsonl"

echo "[smoke] Generating A..." && python bot/scripts/run_replay_obflow.py --out "$RUN_A"
echo "[smoke] Generating B..." && python bot/scripts/run_replay_obflow.py --out "$RUN_B"

echo "[smoke] Comparing fields (step, symbol, meta.type, meta.side, meta.score)"
paste <(jq -r '{s:.step,sy:.symbol,t:.meta.type,sd:.meta.side,sc:.meta.score}|@json' "$RUN_A") \
      <(jq -r '{s:.step,sy:.symbol,t:.meta.type,sd:.meta.side,sc:.meta.score}|@json' "$RUN_B") | diff -u - || true

echo "[smoke] Done"

