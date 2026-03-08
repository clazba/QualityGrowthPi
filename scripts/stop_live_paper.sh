#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
LIQUIDATE_ON_STOP="false"

if [[ "${1:-}" == "--liquidate" ]]; then
  LIQUIDATE_ON_STOP="true"
fi

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

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is not installed. Run make setup first.\n' >&2
  exit 1
fi

LEAN_BACKTEST_PROJECT="${LEAN_BACKTEST_PROJECT:-$DEFAULT_PROJECT}"
PROJECT_SELECTOR="${LEAN_BACKTEST_PROJECT_ID:-${LEAN_BACKTEST_PROJECT:-$DEFAULT_PROJECT}}"
PAPER_DEPLOYMENT_TARGET="${PAPER_DEPLOYMENT_TARGET:-cloud}"

read -r -p "Stop paper deployment for ${PROJECT_SELECTOR} (liquidate=${LIQUIDATE_ON_STOP})? [y/N]: " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  printf 'Paper stop aborted by operator.\n'
  exit 0
fi

cd "$PROJECT_ROOT/lean_workspace"

case "$PAPER_DEPLOYMENT_TARGET" in
  cloud)
    if [[ "$LIQUIDATE_ON_STOP" == "true" ]]; then
      lean cloud live liquidate "$PROJECT_SELECTOR"
    else
      lean cloud live stop "$PROJECT_SELECTOR"
    fi
    ;;
  local)
    if [[ "$LIQUIDATE_ON_STOP" == "true" ]]; then
      lean live liquidate "$LEAN_BACKTEST_PROJECT" --lean-config "$PROJECT_ROOT/lean_workspace/lean.json"
    else
      lean live stop "$LEAN_BACKTEST_PROJECT" --lean-config "$PROJECT_ROOT/lean_workspace/lean.json"
    fi
    ;;
  *)
    printf 'Unsupported PAPER_DEPLOYMENT_TARGET: %s\n' "$PAPER_DEPLOYMENT_TARGET" >&2
    exit 1
    ;;
esac
