#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

BACKTEST_MODE="${BACKTEST_MODE:-cloud}"
LEAN_CLOUD_PUSH_ON_BACKTEST="${LEAN_CLOUD_PUSH_ON_BACKTEST:-true}"
LEAN_CLOUD_OPEN_RESULTS="${LEAN_CLOUD_OPEN_RESULTS:-false}"
LEAN_BACKTEST_PROJECT="${LEAN_BACKTEST_PROJECT:-QualityGrowthPi}"
RESULTS_DIR="${QUANT_GPT_RUNTIME_ROOT:-$PROJECT_ROOT}/results/backtests"
mkdir -p "$RESULTS_DIR"

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is not installed. Run make setup first.\n' >&2
  exit 1
fi

"$PROJECT_ROOT/scripts/sync_lean_config.sh"

read -r -p "Run LEAN backtest for ${LEAN_BACKTEST_PROJECT} in ${BACKTEST_MODE} mode? [y/N]: " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  printf 'Backtest aborted by operator.\n'
  exit 0
fi

cd "$PROJECT_ROOT/lean_workspace"

case "$BACKTEST_MODE" in
  cloud)
    args=("cloud" "backtest" "$LEAN_BACKTEST_PROJECT")
    if [[ "$LEAN_CLOUD_PUSH_ON_BACKTEST" == "true" ]]; then
      args+=("--push")
    fi
    if [[ "$LEAN_CLOUD_OPEN_RESULTS" == "true" ]]; then
      args+=("--open")
    fi
    printf 'Running cloud backtest for %s' "$LEAN_BACKTEST_PROJECT"
    if [[ "$LEAN_CLOUD_PUSH_ON_BACKTEST" == "true" ]]; then
      printf ' with --push'
    fi
    printf '.\n'
    lean "${args[@]}"
    ;;
  local)
    printf 'Running local backtest for %s. Results directory: %s\n' "$LEAN_BACKTEST_PROJECT" "$RESULTS_DIR"
    lean backtest "$LEAN_BACKTEST_PROJECT" --output "$RESULTS_DIR"
    ;;
  *)
    printf 'Unsupported BACKTEST_MODE: %s\n' "$BACKTEST_MODE" >&2
    printf 'Expected "cloud" or "local".\n' >&2
    exit 1
    ;;
esac
