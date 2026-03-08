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

STRATEGY_MODE="${QUANT_GPT_STRATEGY_MODE:-quality_growth}"
DEFAULT_PROJECT="QualityGrowthPi"
if [[ "$STRATEGY_MODE" == "stat_arb_graph_pairs" ]]; then
  DEFAULT_PROJECT="GraphStatArb"
fi
LEAN_PROJECT_NAME="${LEAN_BACKTEST_PROJECT:-$DEFAULT_PROJECT}"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'python3 is required.\n' >&2
  exit 1
fi

restore_default_profile() {
  export QUANT_GPT_SETTINGS_PROFILE="default"
  "$PROJECT_ROOT/scripts/sync_lean_project.sh" >/dev/null
}

trap restore_default_profile EXIT

export QUANT_GPT_SETTINGS_PROFILE="short_regression"

printf 'Running centralized-settings regression checks with profile=%s.\n' "$QUANT_GPT_SETTINGS_PROFILE"
if [[ "$LEAN_PROJECT_NAME" == "GraphStatArb" ]]; then
  "$PYTHON_BIN" -m pytest \
    tests/regression/test_strategy_settings_baseline.py \
    tests/unit/test_stat_arb_graph.py \
    tests/unit/test_stat_arb_ml_filter.py \
    tests/unit/test_stat_arb_risk.py \
    lean_workspace/GraphStatArb/tests/integration/test_project_config.py \
    lean_workspace/GraphStatArb/tests/regression/test_baseline_manifest.py \
    lean_workspace/GraphStatArb/tests/unit/test_graph_stat_arb_import.py
else
  "$PYTHON_BIN" -m pytest \
    tests/regression/test_strategy_settings_baseline.py \
    tests/regression/test_rebalance_regression_scaffold.py \
    tests/regression/test_scoring_regression.py \
    lean_workspace/QualityGrowthPi/tests/integration/test_project_config.py \
    lean_workspace/QualityGrowthPi/tests/regression/test_baseline_manifest.py
fi

printf 'Running short-duration backtest with profile=%s.\n' "$QUANT_GPT_SETTINGS_PROFILE"
export QUANT_GPT_ASSUME_YES=true
"$PROJECT_ROOT/scripts/run_backtest.sh"
