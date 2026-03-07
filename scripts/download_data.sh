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

RUNTIME_ROOT="${QUANT_GPT_RUNTIME_ROOT:-$PROJECT_ROOT}"
LEAN_DATA_DIRECTORY="${LEAN_DATA_DIRECTORY:-$RUNTIME_ROOT/data/lean}"
BACKTEST_MODE="${BACKTEST_MODE:-cloud}"

mkdir -p "$LEAN_DATA_DIRECTORY" "$RUNTIME_ROOT/data/news_cache" "$RUNTIME_ROOT/data/market_cache"

printf 'Prepared local data directories under %s\n' "$RUNTIME_ROOT/data"
printf 'LEAN data directory: %s\n' "$LEAN_DATA_DIRECTORY"
printf 'Configured backtest mode: %s\n' "$BACKTEST_MODE"

if [[ "$BACKTEST_MODE" == "cloud" ]]; then
  printf 'Cloud backtests do not require local LEAN dataset downloads. Local data is only needed for local backtests or fully local execution.\n'
fi

if command -v lean >/dev/null 2>&1; then
  if [[ "$BACKTEST_MODE" == "local" ]]; then
    "$PROJECT_ROOT/scripts/sync_lean_config.sh"
    printf 'LEAN CLI detected. Data download remains operator-driven because dataset entitlements vary.\n'
    printf 'Use your licensed LEAN data workflow and point it at: %s\n' "$LEAN_DATA_DIRECTORY"
  else
    printf 'LEAN CLI detected. Skipping LEAN workspace sync because BACKTEST_MODE=cloud.\n'
    printf 'If you later switch to local backtests, set BACKTEST_MODE=local and rerun this script before downloading datasets.\n'
  fi
else
  printf 'LEAN CLI not installed; cannot stage LEAN datasets automatically.\n'
fi

printf 'Place curated JSONL news feeds under: %s\n' "$RUNTIME_ROOT/data/news_cache"
