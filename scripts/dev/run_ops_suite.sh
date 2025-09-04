#!/usr/bin/env bash
set -euo pipefail
pytest -q -m "ops" --maxfail=1 --disable-warnings

