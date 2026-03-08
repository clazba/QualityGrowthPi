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

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'python3 is required.\n' >&2
  exit 1
fi

RUN_BACKTEST=false
CAPTURE_BASELINE=false
INCLUDE_PAPER_STATUS=true
BACKTEST_ID=""

usage() {
  cat <<'EOF'
Usage: ./scripts/run_trade_workflow.sh [options]

Options:
  --run-backtest         Execute a fresh cloud backtest first.
  --backtest-id ID       Use a specific cloud backtest id instead of the latest.
  --capture-baseline     Capture the resolved backtest as a regression baseline.
  --skip-paper-status    Do not query the current paper deployment / Alpaca positions.
  -h, --help             Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-backtest)
      RUN_BACKTEST=true
      shift
      ;;
    --backtest-id)
      BACKTEST_ID="${2:-}"
      if [[ -z "$BACKTEST_ID" ]]; then
        printf '%s\n' '--backtest-id requires a value.' >&2
        exit 1
      fi
      shift 2
      ;;
    --capture-baseline)
      CAPTURE_BASELINE=true
      shift
      ;;
    --skip-paper-status)
      INCLUDE_PAPER_STATUS=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

RUNTIME_ROOT="${QUANT_GPT_RUNTIME_ROOT:-$PROJECT_ROOT}"
REPORT_ROOT="$RUNTIME_ROOT/results/opportunities"
BACKTEST_ROOT="$RUNTIME_ROOT/results/backtests/cloud"
STRATEGY_MODE="${QUANT_GPT_STRATEGY_MODE:-quality_growth}"
if [[ "$STRATEGY_MODE" == "stat_arb_graph_pairs" ]]; then
  LEAN_CONFIG_PATH="$PROJECT_ROOT/lean_workspace/GraphStatArb/config.py"
else
  LEAN_CONFIG_PATH="$PROJECT_ROOT/lean_workspace/QualityGrowthPi/config.py"
fi
mkdir -p "$REPORT_ROOT" "$BACKTEST_ROOT"

if [[ "$RUN_BACKTEST" == "true" ]]; then
  printf 'Running a fresh cloud backtest as part of the trade workflow.\n'
  printf 'y\n' | "$PROJECT_ROOT/scripts/run_backtest.sh"
fi

if [[ -n "$BACKTEST_ID" ]]; then
  "$PROJECT_ROOT/scripts/read_backtest_diagnostics.sh" "$BACKTEST_ID"
  DIAGNOSTICS_JSON="$BACKTEST_ROOT/$BACKTEST_ID.json"
else
  "$PROJECT_ROOT/scripts/read_backtest_diagnostics.sh"
  DIAGNOSTICS_JSON="$(ls -1t "$BACKTEST_ROOT"/*.json 2>/dev/null | head -n 1)"
fi

if [[ -z "${DIAGNOSTICS_JSON:-}" || ! -f "$DIAGNOSTICS_JSON" ]]; then
  printf 'Unable to locate a diagnostics JSON file under %s.\n' "$BACKTEST_ROOT" >&2
  exit 1
fi

PAPER_STATUS_FILE="$REPORT_ROOT/paper_status_latest.txt"
POSITIONS_FILE="$REPORT_ROOT/paper_positions_latest.json"
LLM_SUMMARY_FILE="$REPORT_ROOT/llm_workflow_latest.json"
STAT_ARB_SUMMARY_FILE="$REPORT_ROOT/stat_arb_workflow_latest.json"

if [[ "$INCLUDE_PAPER_STATUS" == "true" ]]; then
  if "$PROJECT_ROOT/scripts/paper_status.sh" >"$PAPER_STATUS_FILE" 2>&1; then
    :
  else
    printf 'paper status unavailable\n' >"$PAPER_STATUS_FILE"
  fi
fi

TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
REPORT_PATH="$REPORT_ROOT/trade_workflow_${TIMESTAMP}.md"

"$PYTHON_BIN" - "$DIAGNOSTICS_JSON" "$PAPER_STATUS_FILE" "$POSITIONS_FILE" "$LLM_SUMMARY_FILE" "$STAT_ARB_SUMMARY_FILE" "$REPORT_PATH" "$LEAN_CONFIG_PATH" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.operator_workflow import (
    build_pair_trade_contexts,
    build_candidate_contexts,
    build_workflow_report,
    fetch_alpaca_account_and_positions,
    load_lean_strategy_config,
    run_stat_arb_operator_cycle,
    run_operator_advisories,
)
from src.settings import load_settings
from src.state_store import StateStore

diagnostics_path = Path(sys.argv[1])
paper_status_path = Path(sys.argv[2])
positions_path = Path(sys.argv[3])
llm_summary_path = Path(sys.argv[4])
stat_arb_summary_path = Path(sys.argv[5])
report_path = Path(sys.argv[6])
config_path = Path(sys.argv[7])

settings = load_settings()
settings.ensure_directories()
store = StateStore(settings.state_db_path)
store.initialize()

diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
paper_status_text = paper_status_path.read_text(encoding="utf-8").strip() if paper_status_path.exists() else "not requested"
positions_payload = fetch_alpaca_account_and_positions()
positions_path.write_text(json.dumps(positions_payload, indent=2, sort_keys=True), encoding="utf-8")
stat_arb_summary = None
if settings.runtime.strategy_mode.value == "stat_arb_graph_pairs":
    try:
        portfolio_equity = float(positions_payload.get("account", {}).get("equity", 0) or 0)
    except (TypeError, ValueError):
        portfolio_equity = 0.0
    if portfolio_equity <= 0:
        portfolio_equity = float(settings.execution.initial_cash)
    stat_arb_summary = run_stat_arb_operator_cycle(
        settings=settings,
        store=store,
        portfolio_equity=portfolio_equity,
    )
    contexts = build_pair_trade_contexts(stat_arb_summary)
    stat_arb_summary_path.write_text(json.dumps(stat_arb_summary, indent=2, sort_keys=True), encoding="utf-8")
else:
    contexts = build_candidate_contexts(
        positions_payload=positions_payload,
        max_symbols=settings.llm.max_symbols_per_batch,
    )
llm_summary = run_operator_advisories(settings=settings, store=store, contexts=contexts)
llm_summary_path.write_text(json.dumps(llm_summary, indent=2, sort_keys=True), encoding="utf-8")

config = load_lean_strategy_config(config_path)
report = build_workflow_report(
    diagnostics=diagnostics,
    config=config,
    paper_status_text=paper_status_text,
    positions_payload=positions_payload,
    llm_summary=llm_summary,
    stat_arb_summary=stat_arb_summary,
)
report_path.write_text(report, encoding="utf-8")
store.close()

print(report)
if stat_arb_summary is not None:
    print(f"\nSaved stat-arb summary to {stat_arb_summary_path}")
print(f"\nSaved LLM summary to {llm_summary_path}")
print(f"Saved report to {report_path}")
PY

RESOLVED_BACKTEST_ID="$("$PYTHON_BIN" - "$DIAGNOSTICS_JSON" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

diagnostics = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(diagnostics["summary"]["backtest_id"])
PY
)"

if [[ "$CAPTURE_BASELINE" == "true" ]]; then
  "$PROJECT_ROOT/scripts/capture_cloud_baseline.sh" "$RESOLVED_BACKTEST_ID"
fi
