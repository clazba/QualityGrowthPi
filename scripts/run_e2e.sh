#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E2E_RUNTIME_ROOT="${QUANT_GPT_E2E_RUNTIME_ROOT:-$PROJECT_ROOT/results/e2e/runtime}"
RUNTIME_ROOT="$E2E_RUNTIME_ROOT"
RESULTS_ROOT="${RUNTIME_ROOT}/results/e2e"
LOG_ROOT="${RUNTIME_ROOT}/logs"
STATE_ROOT="${RUNTIME_ROOT}/state"
ENV_FILE="${PROJECT_ROOT}/.env"
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
LOG_FILE="${LOG_ROOT}/run_e2e_${STAMP}.log"
SUMMARY_FILE="${RESULTS_ROOT}/summary_${STAMP}.tsv"
PROVIDER_PLAN_FILE="${RESULTS_ROOT}/provider_plan_${STAMP}.json"
STATE_REPORT_FILE="${RESULTS_ROOT}/state_report_${STAMP}.json"
LEAN_REPORT_FILE="${RESULTS_ROOT}/lean_report_${STAMP}.json"
FIXTURE_DIR="${RESULTS_ROOT}/fixtures"
FIXTURE_NEWS_FILE="${FIXTURE_DIR}/news_feed.jsonl"

RUN_ONLINE_CHECKS=false
RUN_CLOUD_BACKTEST=false
RUN_PAPER_DEPLOY=false

PASS_COUNT=0
SKIP_COUNT=0

mkdir -p "$RESULTS_ROOT" "$LOG_ROOT" "$STATE_ROOT" "$FIXTURE_DIR"
touch "$LOG_FILE" "$SUMMARY_FILE"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'python3 is required for the e2e script.\n' >&2
  exit 1
fi

export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export QUANT_GPT_RUNTIME_ROOT="$RUNTIME_ROOT"
export QUANT_GPT_STATE_DB="${STATE_ROOT}/quant_gpt_e2e.db"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

usage() {
  cat <<'EOF'
Usage: ./scripts/run_e2e.sh [options]

Options:
  --online               Enable non-destructive online checks for LEAN and configured providers.
  --run-cloud-backtest   Execute the configured cloud/local backtest after preflight checks.
  --run-paper-deploy     Execute the configured paper deployment after preflight checks.
  --help                 Show this help.

Default behavior is non-destructive:
  - runs verification, tests, smoke flows, state-store checks, provider-plan checks
  - performs LEAN/backtest and paper deployment preflight only
  - does not place orders or start a cloud backtest unless explicitly requested
EOF
}

log() {
  printf '%s | %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "$LOG_FILE"
}

record_status() {
  local status="$1"
  local step="$2"
  local detail="$3"
  printf '%s\t%s\t%s\n' "$status" "$step" "$detail" >>"$SUMMARY_FILE"
}

mark_pass() {
  local step="$1"
  local detail="${2:-ok}"
  PASS_COUNT=$((PASS_COUNT + 1))
  record_status "PASS" "$step" "$detail"
  log "PASS | ${step} | ${detail}"
}

mark_skip() {
  local step="$1"
  local detail="$2"
  SKIP_COUNT=$((SKIP_COUNT + 1))
  record_status "SKIP" "$step" "$detail"
  log "SKIP | ${step} | ${detail}"
}

run_step() {
  local step="$1"
  shift
  log "START | ${step}"
  if "$@" 2>&1 | tee -a "$LOG_FILE"; then
    mark_pass "$step"
  else
    record_status "FAIL" "$step" "command failed"
    log "FAIL | ${step}"
    exit 1
  fi
}

run_python_step() {
  local step="$1"
  log "START | ${step}"
  if (
    cd "$PROJECT_ROOT"
    "$PYTHON_BIN" -
  ) 2>&1 | tee -a "$LOG_FILE"; then
    mark_pass "$step"
  else
    record_status "FAIL" "$step" "python check failed"
    log "FAIL | ${step}"
    exit 1
  fi
}

run_optional_python_step() {
  local step="$1"
  local skip_detail="$2"
  log "START | ${step}"
  if (
    cd "$PROJECT_ROOT"
    "$PYTHON_BIN" -
  ) 2>&1 | tee -a "$LOG_FILE"; then
    mark_pass "$step"
  else
    mark_skip "$step" "$skip_detail"
  fi
}

confirm() {
  local prompt="$1"
  read -r -p "$prompt [y/N]: " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

have_env_file() {
  [[ -f "$ENV_FILE" ]]
}

have_lean() {
  command -v lean >/dev/null 2>&1
}

resolve_env_value() {
  local key="$1"
  "$PYTHON_BIN" - "$PROJECT_ROOT/.env" "$key" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
key = sys.argv[2]

if not env_path.exists():
    raise SystemExit(0)

for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    lhs, rhs = line.split("=", 1)
    if lhs.strip() != key:
        continue
    rhs = rhs.strip()
    if len(rhs) >= 2 and rhs[0] == rhs[-1] and rhs[0] in {"'", '"'}:
        print(rhs[1:-1])
    else:
        print(rhs)
    break
PY
}

lean_preflight_available() {
  if ! have_env_file || ! have_lean; then
    return 1
  fi
  local org_id
  org_id="${LEAN_ORGANIZATION_ID:-$(resolve_env_value "LEAN_ORGANIZATION_ID")}"
  [[ -n "$org_id" && ! "$org_id" =~ [[:space:]] ]]
}

alpaca_credentials_available() {
  local key secret
  key="${ALPACA_API_KEY:-$(resolve_env_value "ALPACA_API_KEY")}"
  secret="${ALPACA_API_SECRET:-$(resolve_env_value "ALPACA_API_SECRET")}"
  [[ -n "$key" && -n "$secret" ]]
}

massive_credentials_available() {
  local key
  key="${MASSIVE_API_KEY:-$(resolve_env_value "MASSIVE_API_KEY")}"
  [[ -n "$key" ]]
}

alpha_vantage_credentials_available() {
  local key
  key="${ALPHA_VANTAGE_API_KEY:-$(resolve_env_value "ALPHA_VANTAGE_API_KEY")}"
  [[ -n "$key" ]]
}

write_fixture_news_feed() {
  cat >"$FIXTURE_NEWS_FILE" <<'EOF'
{"event_id":"e2e-aapl-001","symbol":"AAPL","headline":"E2E fixture Apple headline","body":"Fixture narrative for Apple.","source":"e2e-fixture","published_at":"2026-01-05T14:30:00+00:00","url":"https://example.test/apple"}
{"event_id":"e2e-msft-001","symbol":"MSFT","headline":"E2E fixture Microsoft headline","body":"Fixture narrative for Microsoft.","source":"e2e-fixture","published_at":"2026-01-05T15:00:00+00:00","url":"https://example.test/microsoft"}
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --online)
      RUN_ONLINE_CHECKS=true
      ;;
    --run-cloud-backtest)
      RUN_CLOUD_BACKTEST=true
      ;;
    --run-paper-deploy)
      RUN_PAPER_DEPLOY=true
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "$RUN_CLOUD_BACKTEST" == "true" && "$RUN_ONLINE_CHECKS" != "true" ]]; then
  printf '--run-cloud-backtest requires --online.\n' >&2
  exit 1
fi

if [[ "$RUN_PAPER_DEPLOY" == "true" && "$RUN_ONLINE_CHECKS" != "true" ]]; then
  printf '--run-paper-deploy requires --online.\n' >&2
  exit 1
fi

log "E2E runtime root: $RUNTIME_ROOT"
log "E2E state db: $QUANT_GPT_STATE_DB"
log "E2E results root: $RESULTS_ROOT"
log "Selected Python: $PYTHON_BIN"
record_status "INFO" "context" "runtime_root=$RUNTIME_ROOT"

run_step "verify_install" "$PROJECT_ROOT/scripts/verify_install.sh"
run_step "download_data_prepare" "$PROJECT_ROOT/scripts/download_data.sh"

run_python_step "control_plane_init_and_report" <<PY
import json
from pathlib import Path

from src.main import main
from src.provider_adapters.factory import resolve_provider_plan
from src.settings import load_settings

settings = load_settings()
provider_plan = resolve_provider_plan(settings).as_dict()
Path("$PROVIDER_PLAN_FILE").write_text(json.dumps(provider_plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(provider_plan, indent=2, sort_keys=True))

raise SystemExit(main())
PY

run_step "control_plane_init_db" "$PYTHON_BIN" -m src.main init-db
run_step "control_plane_health" "$PYTHON_BIN" -m src.main health
run_step "control_plane_llm_report" "$PYTHON_BIN" -m src.main llm-report

run_python_step "state_store_validation" <<PY
import json
from pathlib import Path

from src.state_store import StateStore

db_path = Path("$QUANT_GPT_STATE_DB")
if not db_path.exists():
    raise SystemExit(f"State DB was not created: {db_path}")

required_tables = {
    "schema_migrations",
    "rebalance_runs",
    "holdings_snapshots",
    "audit_events",
    "provider_cache",
    "llm_cache",
    "sentiment_snapshots",
    "advisory_history",
    "llm_usage",
}

store = StateStore(db_path)
try:
    conn = store.connection
    journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    audit_count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
finally:
    store.close()

missing = sorted(required_tables - tables)
if journal_mode.lower() != "wal":
    raise SystemExit(f"Expected WAL mode, received {journal_mode}")
if foreign_keys != 1:
    raise SystemExit("SQLite foreign_keys pragma is not enabled")
if busy_timeout < 5000:
    raise SystemExit(f"Expected busy_timeout >= 5000, received {busy_timeout}")
if missing:
    raise SystemExit(f"Missing required state tables: {missing}")
if audit_count < 1:
    raise SystemExit("Expected at least one audit event after health command")

report = {
    "db_path": str(db_path),
    "journal_mode": journal_mode,
    "foreign_keys": foreign_keys,
    "busy_timeout": busy_timeout,
    "audit_event_count": audit_count,
    "table_count": len(tables),
}
Path("$STATE_REPORT_FILE").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2, sort_keys=True))
PY

write_fixture_news_feed
run_python_step "fixture_news_ingestion" <<PY
from datetime import UTC, datetime
from pathlib import Path
import os

from src.provider_adapters.news_base import FileNewsProvider

provider = FileNewsProvider(Path("$FIXTURE_NEWS_FILE"))
events = provider.fetch_news(["AAPL", "MSFT"], since=datetime(2026, 1, 1, tzinfo=UTC))
if len(events) != 2:
    raise SystemExit(f"Expected 2 fixture events, received {len(events)}")
print(f"Loaded fixture news events={len(events)} source={provider.provider_name()} path={os.fspath(provider.feed_path)}")
PY

run_step "smoke_test" "$PROJECT_ROOT/scripts/smoke_test.sh"
run_step "llm_smoke_test" "$PROJECT_ROOT/scripts/llm_smoke_test.sh"
run_step "full_test_suite" "$PROJECT_ROOT/scripts/run_tests.sh"

if lean_preflight_available; then
  run_step "lean_workspace_sync" "$PROJECT_ROOT/scripts/sync_lean_config.sh"
  run_python_step "lean_workspace_validation" <<PY
import json
from pathlib import Path

lean_json = Path("$PROJECT_ROOT/lean_workspace/lean.json")
payload = json.loads(lean_json.read_text(encoding="utf-8"))
required = {
    "job-organization-id": payload.get("job-organization-id"),
    "data-folder": payload.get("data-folder"),
}
for key, value in required.items():
    if not value:
        raise SystemExit(f"LEAN config missing {key}")
Path("$LEAN_REPORT_FILE").write_text(json.dumps(required, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(required, indent=2, sort_keys=True))
PY
  run_step "backtest_preflight_abort" bash -lc "printf 'n\n' | '$PROJECT_ROOT/scripts/run_backtest.sh'"
else
  mark_skip "lean_workspace_sync" "LEAN CLI or LEAN_ORGANIZATION_ID not configured"
  mark_skip "lean_workspace_validation" "LEAN CLI or LEAN_ORGANIZATION_ID not configured"
  mark_skip "backtest_preflight_abort" "LEAN CLI or LEAN_ORGANIZATION_ID not configured"
fi

if have_env_file && alpaca_credentials_available; then
  run_step "paper_preflight_abort" bash -lc "printf 'n\n' | '$PROJECT_ROOT/scripts/run_live_paper.sh'"
else
  mark_skip "paper_preflight_abort" "Alpaca credentials are not configured"
fi

run_python_step "execution_provider_validation" <<PY
from src.provider_adapters.base import ProviderError
from src.provider_adapters.factory import build_execution_provider
from src.settings import load_settings

settings = load_settings()
provider = build_execution_provider(settings)
print(f"execution_provider={provider.provider_name()}")
try:
    provider.validate(paper=True)
except ProviderError as exc:
    print(f"execution_provider_validation=skipped reason={exc}")
else:
    print("execution_provider_validation=ok")
PY

if [[ "$RUN_ONLINE_CHECKS" == "true" ]]; then
  if have_lean; then
    run_step "lean_whoami" lean whoami
  else
    mark_skip "lean_whoami" "LEAN CLI is not installed"
  fi

  if alpaca_credentials_available; then
    run_optional_python_step "alpaca_market_data_probe" "Alpaca market-data probe did not return usable bars; see log for provider response details" <<PY
from src.provider_adapters.base import ProviderError
from src.provider_adapters.alpaca_adapter import AlpacaMarketDataAdapter

provider = AlpacaMarketDataAdapter()
probe_symbol = "AAPL"
try:
    bars = provider.fetch_daily_bars(probe_symbol, 5)
except ProviderError as exc:
    print(f"alpaca_probe provider={provider.provider_name()} symbol={probe_symbol} status=unusable detail={exc}")
    raise SystemExit(1)
print(
    f"alpaca_probe provider={provider.provider_name()} symbol={probe_symbol} "
    f"closes={len(bars['closes'])} volumes={len(bars['volumes'])}"
)
PY
  else
    mark_skip "alpaca_market_data_probe" "Alpaca credentials are not configured"
  fi

  if alpha_vantage_credentials_available; then
    run_optional_python_step "alpha_vantage_news_probe" "Alpha Vantage news probe failed or returned no usable events; see log for details" <<PY
from datetime import UTC, datetime, timedelta

from src.provider_adapters.alpha_vantage_adapter import AlphaVantageNewsProvider

provider = AlphaVantageNewsProvider()
events = provider.fetch_news(["SPY"], since=datetime.now(UTC) - timedelta(days=7))
print(f"alpha_vantage_probe provider={provider.provider_name()} events={len(events)}")
PY
  else
    mark_skip "alpha_vantage_news_probe" "ALPHA_VANTAGE_API_KEY is not configured"
  fi

  if massive_credentials_available; then
    run_optional_python_step "massive_news_probe" "Massive news probe failed or returned no usable events; see log for details" <<PY
from datetime import UTC, datetime, timedelta

from src.provider_adapters.news_base import MassiveNewsProvider

provider = MassiveNewsProvider()
events = provider.fetch_news(["SPY"], since=datetime.now(UTC) - timedelta(days=7))
print(f"massive_probe provider={provider.provider_name()} events={len(events)}")
PY
  else
    mark_skip "massive_news_probe" "MASSIVE_API_KEY is not configured"
  fi
fi

if [[ "$RUN_CLOUD_BACKTEST" == "true" ]]; then
  if confirm "Execute the configured LEAN backtest now?"; then
    run_step "cloud_backtest_execute" bash -lc "printf 'y\n' | '$PROJECT_ROOT/scripts/run_backtest.sh'"
  else
    mark_skip "cloud_backtest_execute" "Operator declined execution"
  fi
fi

if [[ "$RUN_PAPER_DEPLOY" == "true" ]]; then
  if confirm "Execute the configured paper deployment now?"; then
    run_step "paper_deploy_execute" bash -lc "printf 'y\n' | '$PROJECT_ROOT/scripts/run_live_paper.sh'"
  else
    mark_skip "paper_deploy_execute" "Operator declined execution"
  fi
fi

log "E2E completed: passed=${PASS_COUNT} skipped=${SKIP_COUNT}"
log "Summary file: $SUMMARY_FILE"
log "Provider plan file: $PROVIDER_PLAN_FILE"
log "State report file: $STATE_REPORT_FILE"
