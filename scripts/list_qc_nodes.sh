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

PROJECT_ID="${1:-${LEAN_BACKTEST_PROJECT_ID:-}}"
if [[ -z "$PROJECT_ID" ]]; then
  printf 'Provide a project id as the first argument or set LEAN_BACKTEST_PROJECT_ID in .env.\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - "$PROJECT_ID" <<'PY'
from __future__ import annotations

import json
import os
import sys
from base64 import b64encode
from hashlib import sha256
from time import time

import requests

BASE_URL = "https://www.quantconnect.com/api/v2"
project_id = int(sys.argv[1])
user_id = os.getenv("QUANTCONNECT_USER_ID", "").strip()
api_token = os.getenv("QUANTCONNECT_API_TOKEN", "").strip()

if not user_id or not api_token:
    raise SystemExit(
        "QUANTCONNECT_USER_ID and QUANTCONNECT_API_TOKEN are required. "
        "Populate them in .env or export them in the current shell."
    )

timestamp = f"{int(time())}"
hashed_token = sha256(f"{api_token}:{timestamp}".encode("utf-8")).hexdigest()
authorization = b64encode(f"{user_id}:{hashed_token}".encode("utf-8")).decode("ascii")
headers = {
    "Authorization": f"Basic {authorization}",
    "Timestamp": timestamp,
}

response = requests.post(
    f"{BASE_URL}/projects/nodes/read",
    headers=headers,
    json={"projectId": project_id},
    timeout=20,
)
response.raise_for_status()
payload = response.json()
if not payload.get("success"):
    raise SystemExit(f"QuantConnect API returned success=false errors={payload.get('errors')}")

nodes = payload.get("nodes", {})
live_nodes = list(nodes.get("live", []))
if not live_nodes:
    raise SystemExit(f"No live nodes were returned for project {project_id}.")

print("id\tname\tsku\tactive\tbusy\tusedBy\tprojectName\tmonthlyUSD")
for node in sorted(live_nodes, key=lambda item: str(item.get("name", "")).lower()):
    print(
        f"{node.get('id')}\t"
        f"{node.get('name')}\t"
        f"{node.get('sku')}\t"
        f"{node.get('active')}\t"
        f"{node.get('busy')}\t"
        f"{node.get('usedBy')}\t"
        f"{node.get('projectName')}\t"
        f"{node.get('price', {}).get('monthly')}"
    )

active = [node for node in live_nodes if node.get("active")]
print()
print(json.dumps({"project_id": project_id, "auto_select_node": payload.get("autoSelectNode"), "active_live_nodes": active}, indent=2, sort_keys=True))
PY
