#!/usr/bin/env bash
# run_tests.sh — cdx_trading_code test runner
# Usage examples:
#   ./run_tests.sh                         # 기본: unit+strategy
#   ./run_tests.sh --all                   # 전체 테스트(ops는 creds 없으면 자동 skip)
#   ./run_tests.sh --ops --env .env.testnet
#   ./run_tests.sh --unit --vv --maxfail 1
#   ./run_tests.sh --all --env .env        # .env 로드 후 전체

set -euo pipefail

# -------- defaults --------
MODE="unit"               # unit | ops | all
ENV_FILE=".env"               # e.g. .env.testnet
PYTEST_VV=""              # --vv if set
MAXFAIL=1
EXTRA_OPTS=()
LOG_CLI="--log-cli-level=INFO -o log_cli=true --durations=10"
TIMEOUT_MARKER=""

print_help() {
  cat <<'EOF'
Usage: run_tests.sh [--unit|--ops|--all] [--env FILE] [--vv] [--maxfail N] [--no-log] [--no-timeout] [--] [extra pytest args]

Modes:
  --unit        : unit + strategy (기본값)
  --ops         : ops + integration (테스트넷; TESTNET=true & BYBIT creds 필요)
  --all         : 전체 수집 (ops는 creds 없으면 conftest에서 자동 skip)

Options:
  --env FILE    : 환경변수 파일을 로드 (예: .env.testnet, .env)
  --vv          : pytest -vv
  --maxfail N   : pytest --maxfail N (기본 1)
  --no-log      : log_cli 비활성화 (기본은 INFO로 활성)
  --no-timeout  : pytest-timeout 마커/플러그인 사용 안함
  --            : 이후 인자는 그대로 pytest에 전달

Examples:
  ./run_tests.sh --unit
  ./run_tests.sh --ops --env .env.testnet
  ./run_tests.sh --all --vv --maxfail 2 -- -k "order or signal"
EOF
}

# -------- arg parse --------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --unit) MODE="unit"; shift ;;
    --ops) MODE="ops"; shift ;;
    --all) MODE="all"; shift ;;
    --env) ENV_FILE="${2:-}"; shift 2 ;;
    --vv) PYTEST_VV="--vv"; shift ;;
    --maxfail) MAXFAIL="${2:-1}"; shift 2 ;;
    --no-log) LOG_CLI=""; shift ;;
    --no-timeout) TIMEOUT_MARKER="--disable-timeout"; shift ;;
    -h|--help) print_help; exit 0 ;;
    --) shift; EXTRA_OPTS+=("$@"); break ;;
    *) EXTRA_OPTS+=("$1"); shift ;;
  esac
done

# -------- env load --------
if [[ -n "$ENV_FILE" ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    echo ">> loading env from $ENV_FILE"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  else
    echo "!! env file not found: $ENV_FILE"
    exit 1
  fi
fi

# -------- helpers --------
have_testnet_creds() {
  [[ "${TESTNET:-false}" == "true" ]] && [[ -n "${BYBIT_API_KEY:-}" ]] && [[ -n "${BYBIT_API_SECRET:-}" ]]
}

# -------- mode to markers --------
case "$MODE" in
  unit) MARKERS='-m "unit or strategy"' ;;
  ops)  MARKERS='-m "ops or integration"' ;;
  all)  MARKERS='' ;;  # conftest가 ops/integration을 자동 skip
  *) echo "unknown mode: $MODE"; exit 1 ;;
esac

# -------- informative banner --------
echo "============ cdx_trading_code test runner ============"
echo "Mode        : $MODE"
echo "Env file    : ${ENV_FILE:-<none>}"
echo "TESTNET     : ${TESTNET:-<unset>}"
echo "BYBIT_KEY   : $( [[ -n "${BYBIT_API_KEY:-}" ]] && echo set || echo unset )"
echo "BYBIT_SECRET: $( [[ -n "${BYBIT_API_SECRET:-}" ]] && echo set || echo unset )"
echo "Pytest opts : $PYTEST_VV --maxfail $MAXFAIL $MARKERS $LOG_CLI ${EXTRA_OPTS[*]}"
echo "======================================================"

# -------- guard for ops --------
if [[ "$MODE" == "ops" ]]; then
  if ! have_testnet_creds; then
    echo "!! Missing TESTNET creds (TESTNET=true & BYBIT_API_KEY/SECRET required)."
    echo "   e.g. run with: --env .env.testnet  or export envs in shell."
    exit 2
  fi
fi

# -------- timeout plugin (optional) --------
# If user didn't disable timeouts and pytest-timeout is installed,
# we add a soft default via env (doesn't break if plugin missing).
if [[ -z "$TIMEOUT_MARKER" ]]; then
  export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} --timeout=60"
fi

# -------- run pytest --------
set -x
pytest $PYTEST_VV --maxfail "$MAXFAIL" $MARKERS $LOG_CLI --disable-warnings "${EXTRA_OPTS[@]}"
