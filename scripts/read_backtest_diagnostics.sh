#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
LEAN_PROJECT_DIR="$PROJECT_ROOT/lean_workspace"
LEAN_PROJECT_NAME="${LEAN_BACKTEST_PROJECT:-QualityGrowthPi}"

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

PROJECT_ID="${LEAN_BACKTEST_PROJECT_ID:-}"
BACKTEST_ID="${1:-}"

if [[ -z "$PROJECT_ID" ]]; then
  printf 'LEAN_BACKTEST_PROJECT_ID is required in .env.\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - "$PROJECT_ID" "$BACKTEST_ID" <<'PY'
from __future__ import annotations

import json
import os
import sys
from base64 import b64encode
from hashlib import sha256
from pathlib import Path
from time import time
from typing import Any, Dict, List, Optional

import requests

BASE_URL = "https://www.quantconnect.com/api/v2"
project_id = int(sys.argv[1])
requested_backtest_id = sys.argv[2].strip()
user_id = os.getenv("QUANTCONNECT_USER_ID", "").strip()
api_token = os.getenv("QUANTCONNECT_API_TOKEN", "").strip()
results_root = Path(os.getenv("QUANT_GPT_RUNTIME_ROOT", Path.cwd())) / "results" / "backtests" / "cloud"
results_root.mkdir(parents=True, exist_ok=True)

if not user_id or not api_token:
    raise SystemExit("QUANTCONNECT_USER_ID and QUANTCONNECT_API_TOKEN are required.")


def get_headers() -> Dict[str, str]:
    timestamp = f"{int(time())}"
    hashed_token = sha256(f"{api_token}:{timestamp}".encode("utf-8")).hexdigest()
    authentication = b64encode(f"{user_id}:{hashed_token}".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {authentication}",
        "Timestamp": timestamp,
    }


def post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload, timeout=30)
    response.raise_for_status()
    decoded = response.json()
    if not decoded.get("success", False):
        raise RuntimeError(f"{endpoint} failed: {decoded.get('errors')}")
    return decoded


def normalize_orders(raw_orders: Any) -> List[Dict[str, Any]]:
    if isinstance(raw_orders, list):
        return [item for item in raw_orders if isinstance(item, dict)]
    if isinstance(raw_orders, dict):
        normalized = []
        for key in sorted(raw_orders.keys(), key=lambda value: int(str(value)) if str(value).isdigit() else str(value)):
            item = raw_orders[key]
            if isinstance(item, dict):
                normalized.append(item)
        return normalized
    return []


def read_all_orders(
    project_id: int,
    backtest_id: str,
    expected_total: Optional[int] = None,
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    start = 0
    all_orders: List[Dict[str, Any]] = []
    seen_order_ids = set()
    while True:
        payload = post(
            "/backtests/orders/read",
            {
                "projectId": project_id,
                "backtestId": backtest_id,
                "start": start,
                "end": start + page_size,
            },
        )
        batch = normalize_orders(payload.get("orders", []))
        if not batch:
            break
        new_orders = []
        for item in batch:
            order_id = item.get("id")
            if order_id in seen_order_ids:
                continue
            seen_order_ids.add(order_id)
            new_orders.append(item)
        if not new_orders:
            break
        all_orders.extend(new_orders)
        if expected_total is not None and len(all_orders) >= expected_total:
            break
        if len(new_orders) < page_size:
            break
        start += len(new_orders)
    return all_orders


backtests_payload = post("/backtests/list", {"projectId": project_id, "includeStatistics": True})
backtests = list(backtests_payload.get("backtests", []))
if not backtests:
    raise SystemExit(f"No backtests returned for project {project_id}")

if requested_backtest_id:
    matches = [item for item in backtests if str(item.get("backtestId", "")) == requested_backtest_id]
    if not matches:
        raise SystemExit(f'Backtest id "{requested_backtest_id}" was not found in project {project_id}')
    selected = matches[0]
else:
    selected = sorted(backtests, key=lambda item: str(item.get("created", "")), reverse=True)[0]

backtest_id = str(selected.get("backtestId"))
detail_payload = post("/backtests/read", {"projectId": project_id, "backtestId": backtest_id})

backtest = dict(detail_payload.get("backtest", {}))
reported_total_orders = int(str(backtest.get("statistics", {}).get("Total Orders", "0")).replace(",", ""))
orders = read_all_orders(project_id, backtest_id, expected_total=reported_total_orders or None)

summary = {
    "project_id": project_id,
    "backtest_id": backtest_id,
    "backtest_url": f"https://www.quantconnect.com/project/{project_id}/{backtest_id}",
    "name": backtest.get("name"),
    "created": backtest.get("created"),
    "status": backtest.get("status"),
    "completed": backtest.get("completed"),
    "progress": backtest.get("progress"),
    "has_initialize_error": backtest.get("hasInitializeError"),
    "error": backtest.get("error"),
    "statistics": backtest.get("statistics", {}),
    "runtime_statistics": backtest.get("runtimeStatistics", {}),
    "reported_total_orders": reported_total_orders,
    "order_count": len(orders),
    "order_ids": [item.get("id") for item in orders[:20]],
    "closed_trade_count": len(backtest.get("totalPerformance", {}).get("closedTrades", [])),
}

out_path = results_root / f"{backtest_id}.json"
out_path.write_text(json.dumps({"summary": summary, "orders": orders, "backtest": backtest}, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
print(f"Saved diagnostics JSON to {out_path}")
PY

if command -v lean >/dev/null 2>&1; then
  printf '\nRecent LEAN cloud logs for %s/%s:\n' "$LEAN_PROJECT_DIR" "$LEAN_PROJECT_NAME"
  LOG_OUTPUT="$(
    cd "$LEAN_PROJECT_DIR"
    lean logs --project "$LEAN_PROJECT_DIR/$LEAN_PROJECT_NAME" --lean-config "$LEAN_PROJECT_DIR/lean.json" --backtest 2>&1
  )" || true
  if [[ "$LOG_OUTPUT" == *"Unable to locate the backtest log file"* ]]; then
    printf 'Cloud log retrieval via LEAN CLI is unavailable for this backtest. Use the saved diagnostics JSON and runtime_statistics instead.\n'
  else
    printf '%s\n' "$LOG_OUTPUT"
  fi
else
  printf '\nLEAN CLI not installed; skipping lean logs.\n'
fi
