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

LEAN_BACKTEST_PROJECT="${LEAN_BACKTEST_PROJECT:-QualityGrowthPi}"
PAPER_DEPLOYMENT_TARGET="${PAPER_DEPLOYMENT_TARGET:-cloud}"
PAPER_BROKER="${PAPER_BROKER:-alpaca}"
PAPER_ENVIRONMENT="${PAPER_ENVIRONMENT:-paper}"
PAPER_LIVE_DATA_PROVIDER="${PAPER_LIVE_DATA_PROVIDER:-QuantConnect}"
PAPER_HISTORICAL_DATA_PROVIDER="${PAPER_HISTORICAL_DATA_PROVIDER:-QuantConnect}"
LEAN_CLOUD_PUSH_ON_PAPER="${LEAN_CLOUD_PUSH_ON_PAPER:-true}"
LEAN_CLOUD_OPEN_PAPER="${LEAN_CLOUD_OPEN_PAPER:-false}"

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is not installed. Run make setup first.\n' >&2
  exit 1
fi

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  printf '.env is required before paper trading. Run make env.\n' >&2
  exit 1
fi

"$PROJECT_ROOT/scripts/sync_lean_config.sh"

if [[ "$PAPER_BROKER" == "alpaca" ]]; then
  if [[ -z "${ALPACA_API_KEY:-}" || -z "${ALPACA_API_SECRET:-}" ]]; then
    printf 'Alpaca paper trading requires ALPACA_API_KEY and ALPACA_API_SECRET in .env.\n' >&2
    exit 1
  fi
fi

read -r -p "Start paper trading for ${LEAN_BACKTEST_PROJECT} using ${PAPER_BROKER} on ${PAPER_DEPLOYMENT_TARGET}? [y/N]: " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  printf 'Paper trading aborted by operator.\n'
  exit 0
fi

cd "$PROJECT_ROOT/lean_workspace"

case "$PAPER_DEPLOYMENT_TARGET" in
  cloud)
    args=("cloud" "live" "deploy" "$LEAN_BACKTEST_PROJECT")
    if [[ "$LEAN_CLOUD_PUSH_ON_PAPER" == "true" ]]; then
      args+=("--push")
    fi
    case "$PAPER_BROKER" in
      alpaca)
        args+=(
          "--brokerage" "Alpaca"
          "--alpaca-environment" "$PAPER_ENVIRONMENT"
          "--alpaca-api-key" "$ALPACA_API_KEY"
          "--alpaca-api-secret" "$ALPACA_API_SECRET"
        )
        ;;
      *)
        printf 'Unsupported PAPER_BROKER for scripted paper deployment: %s\n' "$PAPER_BROKER" >&2
        exit 1
        ;;
    esac
    args+=("--data-provider-live" "$PAPER_LIVE_DATA_PROVIDER")
    args+=("--data-provider-historical" "$PAPER_HISTORICAL_DATA_PROVIDER")
    if [[ "$LEAN_CLOUD_OPEN_PAPER" == "true" ]]; then
      args+=("--open")
    fi
    printf 'Running cloud paper deployment for %s via %s.\n' "$LEAN_BACKTEST_PROJECT" "$PAPER_BROKER"
    lean "${args[@]}"
    ;;
  local)
    if [[ "$PAPER_LIVE_DATA_PROVIDER" == "QuantConnect" ]]; then
      printf 'QuantConnect is not an appropriate local live data provider for the chosen local fallback stack.\n' >&2
      printf 'Override PAPER_LIVE_DATA_PROVIDER to Alpaca or another local provider before using PAPER_DEPLOYMENT_TARGET=local.\n' >&2
      exit 1
    fi
    args=("live" "deploy" "$LEAN_BACKTEST_PROJECT")
    case "$PAPER_BROKER" in
      alpaca)
        args+=(
          "--brokerage" "Alpaca"
          "--alpaca-environment" "$PAPER_ENVIRONMENT"
          "--alpaca-api-key" "$ALPACA_API_KEY"
          "--alpaca-api-secret" "$ALPACA_API_SECRET"
        )
        ;;
      *)
        printf 'Unsupported PAPER_BROKER for scripted paper deployment: %s\n' "$PAPER_BROKER" >&2
        exit 1
        ;;
    esac
    args+=("--data-provider-live" "$PAPER_LIVE_DATA_PROVIDER")
    args+=("--data-provider-historical" "$PAPER_HISTORICAL_DATA_PROVIDER")
    printf 'Running local paper deployment for %s via %s.\n' "$LEAN_BACKTEST_PROJECT" "$PAPER_BROKER"
    lean "${args[@]}"
    ;;
  *)
    printf 'Unsupported PAPER_DEPLOYMENT_TARGET: %s\n' "$PAPER_DEPLOYMENT_TARGET" >&2
    printf 'Expected "cloud" or "local".\n' >&2
    exit 1
    ;;
esac
