#!/usr/bin/env bash
set -euo pipefail
pytest -q -m "strategy" --maxfail=1 --disable-warnings

