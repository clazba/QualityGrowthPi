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
LEAN_BACKTEST_PROJECT_ID="${LEAN_BACKTEST_PROJECT_ID:-}"
QC_CLOUD_FILE_SYNC="${QC_CLOUD_FILE_SYNC:-true}"
PROJECT_SELECTOR="${LEAN_BACKTEST_PROJECT_ID:-$LEAN_BACKTEST_PROJECT}"
PAPER_DEPLOYMENT_TARGET="${PAPER_DEPLOYMENT_TARGET:-cloud}"
PAPER_BROKER="${PAPER_BROKER:-alpaca}"
PAPER_ENVIRONMENT="${PAPER_ENVIRONMENT:-paper}"
PAPER_LIVE_DATA_PROVIDER="${PAPER_LIVE_DATA_PROVIDER:-QuantConnect}"
PAPER_HISTORICAL_DATA_PROVIDER="${PAPER_HISTORICAL_DATA_PROVIDER:-QuantConnect}"
LEAN_CLOUD_PUSH_ON_PAPER="${LEAN_CLOUD_PUSH_ON_PAPER:-true}"
LEAN_CLOUD_PAPER_NODE="${LEAN_CLOUD_PAPER_NODE:-}"
LEAN_CLOUD_PAPER_AUTO_RESTART="${LEAN_CLOUD_PAPER_AUTO_RESTART:-true}"
LEAN_CLOUD_PAPER_NOTIFY_ORDER_EVENTS="${LEAN_CLOUD_PAPER_NOTIFY_ORDER_EVENTS:-true}"
LEAN_CLOUD_PAPER_NOTIFY_INSIGHTS="${LEAN_CLOUD_PAPER_NOTIFY_INSIGHTS:-false}"
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
"$PROJECT_ROOT/scripts/sync_lean_project.sh"

if [[ "$PAPER_BROKER" == "alpaca" ]]; then
  if [[ -z "${ALPACA_API_KEY:-}" || -z "${ALPACA_API_SECRET:-}" ]]; then
    printf 'Alpaca paper trading requires ALPACA_API_KEY and ALPACA_API_SECRET in .env.\n' >&2
    exit 1
  fi
  if [[ "$PAPER_ENVIRONMENT" != "paper" ]]; then
    printf 'scripts/run_live_paper.sh only supports PAPER_ENVIRONMENT=paper.\n' >&2
    exit 1
  fi
fi

if [[ "$PAPER_DEPLOYMENT_TARGET" == "cloud" && -z "$LEAN_CLOUD_PAPER_NODE" ]]; then
  printf 'LEAN_CLOUD_PAPER_NODE is required for non-interactive cloud paper deployment.\n' >&2
  printf 'Use scripts/list_qc_nodes.sh to find an available live node, then set LEAN_CLOUD_PAPER_NODE in .env.\n' >&2
  exit 1
fi

if [[ "$PAPER_BROKER" == "alpaca" ]]; then
  "$PROJECT_ROOT/scripts/check_alpaca_paper.sh"
fi

read -r -p "Start paper trading for ${PROJECT_SELECTOR} using ${PAPER_BROKER} on ${PAPER_DEPLOYMENT_TARGET}? [y/N]: " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  printf 'Paper trading aborted by operator.\n'
  exit 0
fi

cd "$PROJECT_ROOT/lean_workspace"

if [[ "$PAPER_DEPLOYMENT_TARGET" == "cloud" && "$LEAN_CLOUD_OPEN_PAPER" != "true" && -z "${BROWSER:-}" ]]; then
  export BROWSER=/bin/true
fi

case "$PAPER_DEPLOYMENT_TARGET" in
  cloud)
    args=("cloud" "live" "deploy" "$PROJECT_SELECTOR")
    if [[ "$QC_CLOUD_FILE_SYNC" == "true" && -n "$LEAN_BACKTEST_PROJECT_ID" ]]; then
      printf 'Syncing LEAN workspace files to QuantConnect project %s via API.\n' "$LEAN_BACKTEST_PROJECT_ID"
      "$PROJECT_ROOT/scripts/sync_qc_cloud_project.sh"
    elif [[ "$LEAN_CLOUD_PUSH_ON_PAPER" == "true" ]]; then
      printf 'Pushing local cloud project directory %s before paper deployment.\n' "$LEAN_BACKTEST_PROJECT"
      lean cloud push --project "$LEAN_BACKTEST_PROJECT"
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
    if [[ -n "${PAPER_HISTORICAL_DATA_PROVIDER:-}" ]]; then
      printf 'Ignoring PAPER_HISTORICAL_DATA_PROVIDER=%s for cloud paper deployment; the current LEAN CLI only accepts --data-provider-live in cloud mode.\n' "$PAPER_HISTORICAL_DATA_PROVIDER"
    fi
    args+=("--node" "$LEAN_CLOUD_PAPER_NODE")
    args+=("--auto-restart" "$LEAN_CLOUD_PAPER_AUTO_RESTART")
    args+=("--notify-order-events" "$LEAN_CLOUD_PAPER_NOTIFY_ORDER_EVENTS")
    args+=("--notify-insights" "$LEAN_CLOUD_PAPER_NOTIFY_INSIGHTS")
    if [[ "$LEAN_CLOUD_OPEN_PAPER" == "true" ]]; then
      args+=("--open")
    fi
    printf 'Running cloud paper deployment for %s via %s.\n' "$PROJECT_SELECTOR" "$PAPER_BROKER"
    lean "${args[@]}"
    ;;
  local)
    if [[ "$PAPER_LIVE_DATA_PROVIDER" == "QuantConnect" ]]; then
      printf 'QuantConnect is not an appropriate local live data provider for the chosen local fallback stack.\n' >&2
      printf 'Override PAPER_LIVE_DATA_PROVIDER to Alpaca or another local provider before using PAPER_DEPLOYMENT_TARGET=local.\n' >&2
      exit 1
    fi
    args=("live" "deploy" "$PROJECT_SELECTOR")
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
    printf 'Running local paper deployment for %s via %s.\n' "$PROJECT_SELECTOR" "$PAPER_BROKER"
    lean "${args[@]}"
    ;;
  *)
    printf 'Unsupported PAPER_DEPLOYMENT_TARGET: %s\n' "$PAPER_DEPLOYMENT_TARGET" >&2
    printf 'Expected "cloud" or "local".\n' >&2
    exit 1
    ;;
esac
