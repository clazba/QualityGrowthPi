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

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is not installed. Run make setup first.\n' >&2
  exit 1
fi

PROJECT_SELECTOR="${LEAN_BACKTEST_PROJECT_ID:-${LEAN_BACKTEST_PROJECT:-QualityGrowthPi}}"
PAPER_DEPLOYMENT_TARGET="${PAPER_DEPLOYMENT_TARGET:-cloud}"

cd "$PROJECT_ROOT/lean_workspace"

case "$PAPER_DEPLOYMENT_TARGET" in
  cloud)
    lean cloud status "$PROJECT_SELECTOR"
    ;;
  local)
    printf 'No dedicated local paper status helper is implemented. Inspect the latest local LEAN live container/logs directly.\n' >&2
    exit 1
    ;;
  *)
    printf 'Unsupported PAPER_DEPLOYMENT_TARGET: %s\n' "$PAPER_DEPLOYMENT_TARGET" >&2
    exit 1
    ;;
esac
