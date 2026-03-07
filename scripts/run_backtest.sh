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
LEAN_BACKTEST_PROJECT_ID="${LEAN_BACKTEST_PROJECT_ID:-}"
QC_CLOUD_FILE_SYNC="${QC_CLOUD_FILE_SYNC:-true}"
PROJECT_SELECTOR="${LEAN_BACKTEST_PROJECT_ID:-$LEAN_BACKTEST_PROJECT}"
RESULTS_DIR="${QUANT_GPT_RUNTIME_ROOT:-$PROJECT_ROOT}/results/backtests"
mkdir -p "$RESULTS_DIR"

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is not installed. Run make setup first.\n' >&2
  exit 1
fi

"$PROJECT_ROOT/scripts/sync_lean_config.sh"
"$PROJECT_ROOT/scripts/sync_lean_project.sh"

read -r -p "Run LEAN backtest for ${PROJECT_SELECTOR} in ${BACKTEST_MODE} mode? [y/N]: " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  printf 'Backtest aborted by operator.\n'
  exit 0
fi

cd "$PROJECT_ROOT/lean_workspace"

case "$BACKTEST_MODE" in
  cloud)
    args=("cloud" "backtest" "$PROJECT_SELECTOR")
    if [[ "$QC_CLOUD_FILE_SYNC" == "true" && -n "$LEAN_BACKTEST_PROJECT_ID" ]]; then
      printf 'Syncing LEAN workspace files to QuantConnect project %s via API.\n' "$LEAN_BACKTEST_PROJECT_ID"
      "$PROJECT_ROOT/scripts/sync_qc_cloud_project.sh"
    elif [[ "$LEAN_CLOUD_PUSH_ON_BACKTEST" == "true" ]]; then
      printf 'Pushing local cloud project directory %s before backtest.\n' "$LEAN_BACKTEST_PROJECT"
      lean cloud push --project "$LEAN_BACKTEST_PROJECT"
    fi
    if [[ "$LEAN_CLOUD_OPEN_RESULTS" == "true" ]]; then
      args+=("--open")
    fi
    printf 'Running cloud backtest for %s' "$PROJECT_SELECTOR"
    if [[ "$QC_CLOUD_FILE_SYNC" == "true" && -n "$LEAN_BACKTEST_PROJECT_ID" ]]; then
      printf ' after QuantConnect API file sync'
    elif [[ "$LEAN_CLOUD_PUSH_ON_BACKTEST" == "true" ]]; then
      printf ' after explicit cloud push from %s' "$LEAN_BACKTEST_PROJECT"
    fi
    printf '.\n'
    lean "${args[@]}"
    ;;
  local)
    printf 'Running local backtest for %s. Results directory: %s\n' "$PROJECT_SELECTOR" "$RESULTS_DIR"
    lean backtest "$PROJECT_SELECTOR" --output "$RESULTS_DIR"
    ;;
  *)
    printf 'Unsupported BACKTEST_MODE: %s\n' "$BACKTEST_MODE" >&2
    printf 'Expected "cloud" or "local".\n' >&2
    exit 1
    ;;
esac
