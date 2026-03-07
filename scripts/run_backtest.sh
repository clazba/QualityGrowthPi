#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${QUANT_GPT_RUNTIME_ROOT:-$PROJECT_ROOT}/results/backtests"
mkdir -p "$RESULTS_DIR"

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is not installed. Run make setup first.\n' >&2
  exit 1
fi

read -r -p "Run LEAN backtest for QualityGrowthPi? This may use network or Docker depending on local LEAN configuration. [y/N]: " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  printf 'Backtest aborted by operator.\n'
  exit 0
fi

cd "$PROJECT_ROOT/lean_workspace"
printf 'Running backtest. Results directory: %s\n' "$RESULTS_DIR"
lean backtest "QualityGrowthPi" --output "$RESULTS_DIR"
