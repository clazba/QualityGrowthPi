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

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import json
import os
from base64 import b64encode
from hashlib import sha256
from time import time

import requests

BASE_URL = "https://www.quantconnect.com/api/v2"
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
    f"{BASE_URL}/projects/read",
    headers=headers,
    json={"start": 0, "end": 1000},
    timeout=20,
)
response.raise_for_status()
payload = response.json()
if not payload.get("success"):
    raise SystemExit(f"QuantConnect API returned success=false errors={payload.get('errors')}")

projects = payload.get("projects", [])
if not projects:
    raise SystemExit("No cloud projects were returned by QuantConnect.")

print("projectId\tname\tlanguage\tmodified\torganizationId")
for project in sorted(projects, key=lambda item: str(item.get("name", "")).lower()):
    print(
        f"{project.get('projectId')}\t"
        f"{project.get('name')}\t"
        f"{project.get('language')}\t"
        f"{project.get('modified')}\t"
        f"{project.get('organizationId')}"
    )

target_name = os.getenv("LEAN_BACKTEST_PROJECT", "").strip()
if target_name:
    matches = [project for project in projects if str(project.get("name", "")).strip().lower() == target_name.lower()]
    print()
    if matches:
        print("Exact case-insensitive matches for LEAN_BACKTEST_PROJECT:")
        print(json.dumps(matches, indent=2, sort_keys=True))
    else:
        print(f'No exact case-insensitive match found for LEAN_BACKTEST_PROJECT="{target_name}".')
PY
