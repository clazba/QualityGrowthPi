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

BACKTEST_ID="${1:-}"
if [[ -z "$BACKTEST_ID" ]]; then
  printf 'Usage: %s <backtest_id>\n' "$0" >&2
  exit 1
fi

PROJECT_ID="${LEAN_BACKTEST_PROJECT_ID:-}"
if [[ -z "$PROJECT_ID" ]]; then
  printf 'LEAN_BACKTEST_PROJECT_ID is required in .env.\n' >&2
  exit 1
fi

DIAGNOSTICS_PATH="${QUANT_GPT_RUNTIME_ROOT:-$PROJECT_ROOT}/results/backtests/cloud/${BACKTEST_ID}.json"
if [[ ! -f "$DIAGNOSTICS_PATH" ]]; then
  printf 'Missing diagnostics file: %s\n' "$DIAGNOSTICS_PATH" >&2
  printf 'Run ./scripts/read_backtest_diagnostics.sh %s first.\n' "$BACKTEST_ID" >&2
  exit 1
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - "$PROJECT_ROOT" "$DIAGNOSTICS_PATH" "$BACKTEST_ID" "$PROJECT_ID" "$LEAN_PROJECT_NAME" <<'PY'
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

project_root = Path(sys.argv[1]).resolve()
diagnostics_path = Path(sys.argv[2]).resolve()
backtest_id = sys.argv[3]
project_id = int(sys.argv[4])
project_name = sys.argv[5]
baseline_root = project_root / "lean_workspace" / project_name / "tests" / "regression" / "cloud_baselines" / backtest_id
manifest_path = project_root / "lean_workspace" / project_name / "tests" / "regression" / "baseline_manifest.json"

payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
summary = dict(payload.get("summary", {}))
backtest = dict(payload.get("backtest", {}))
orders = list(payload.get("orders", []))
total_performance = dict(backtest.get("totalPerformance", {}))
portfolio_statistics = dict(total_performance.get("portfolioStatistics", {}))
trade_statistics = dict(total_performance.get("tradeStatistics", {}))
closed_trades = list(total_performance.get("closedTrades", []))

baseline_root.mkdir(parents=True, exist_ok=True)

files = {
    "summary.json": summary,
    "runtime_statistics.json": summary.get("runtime_statistics", {}),
    "statistics.json": summary.get("statistics", {}),
    "orders.json": orders,
    "closed_trades.json": closed_trades,
    "portfolio_statistics.json": portfolio_statistics,
    "trade_statistics.json": trade_statistics,
    "baseline_meta.json": {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_diagnostics_path": str(diagnostics_path),
        "source_backtest_id": backtest_id,
        "source_project_id": project_id,
        "backtest_url": summary.get("backtest_url"),
        "order_count": summary.get("order_count"),
        "reported_total_orders": summary.get("reported_total_orders"),
        "closed_trade_count": summary.get("closed_trade_count"),
    },
}

for filename, content in files.items():
    (baseline_root / filename).write_text(json.dumps(content, indent=2, sort_keys=True), encoding="utf-8")

if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
else:
    expected_artifacts = (
        [
            "cluster_snapshots",
            "pair_candidates",
            "ml_filter_decisions",
            "pair_trade_intents",
            "pair_position_state",
            "cloud_baseline_bundles",
        ]
        if project_name == "GraphStatArb"
        else [
            "universe_snapshots",
            "score_tables",
            "target_weights",
            "order_events",
            "holdings_snapshots",
            "cloud_baseline_bundles",
        ]
    )
    manifest = {
        "description": "Baseline artefact slots for future QuantConnect comparison bundles.",
        "expected_artifacts": expected_artifacts,
        "captured_baselines": [],
        "latest_baseline_id": None,
    }
captured_baselines = list(manifest.get("captured_baselines", []))
captured_baselines = [entry for entry in captured_baselines if entry.get("backtest_id") != backtest_id]
captured_baselines.append(
    {
        "backtest_id": backtest_id,
        "project_id": project_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "path": str(baseline_root.relative_to(project_root)),
        "order_count": summary.get("order_count"),
        "reported_total_orders": summary.get("reported_total_orders"),
        "closed_trade_count": summary.get("closed_trade_count"),
        "net_profit": summary.get("statistics", {}).get("Net Profit"),
        "return": summary.get("runtime_statistics", {}).get("Return"),
    }
)
captured_baselines.sort(key=lambda item: str(item.get("captured_at", "")), reverse=True)
manifest["captured_baselines"] = captured_baselines
manifest["latest_baseline_id"] = backtest_id
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

print(
    json.dumps(
        {
            "baseline_root": str(baseline_root),
            "files_written": sorted(files),
            "manifest_path": str(manifest_path),
            "latest_baseline_id": backtest_id,
        },
        indent=2,
        sort_keys=True,
    )
)
PY
