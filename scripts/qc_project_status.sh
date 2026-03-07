#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

MODE="status"
if [[ "${1:-}" == "--acquire-lock" ]]; then
  MODE="acquire-lock"
fi

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
"$PYTHON_BIN" - "$MODE" <<'PY'
from __future__ import annotations

import json
import os
import sys
from base64 import b64encode
from hashlib import sha256
from time import time
from typing import Any, Dict

import requests

BASE_URL = "https://www.quantconnect.com/api/v2"
mode = sys.argv[1]

project_id_raw = os.getenv("LEAN_BACKTEST_PROJECT_ID", "").strip()
user_id = os.getenv("QUANTCONNECT_USER_ID", "").strip()
api_token = os.getenv("QUANTCONNECT_API_TOKEN", "").strip()
code_source_id = os.getenv("QC_CODE_SOURCE_ID", "quant_gpt_cli").strip() or "quant_gpt_cli"

if not project_id_raw:
    raise SystemExit("LEAN_BACKTEST_PROJECT_ID is required.")
if not user_id or not api_token:
    raise SystemExit("QUANTCONNECT_USER_ID and QUANTCONNECT_API_TOKEN are required.")

project_id = int(project_id_raw)


def get_headers() -> Dict[str, str]:
    timestamp = f"{int(time())}"
    hashed_token = sha256(f"{api_token}:{timestamp}".encode("utf-8")).hexdigest()
    authentication = b64encode(f"{user_id}:{hashed_token}".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {authentication}",
        "Timestamp": timestamp,
    }


def post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    return data


project_payload = post("/projects/read", {"projectId": project_id})
collab_payload = post("/projects/collaboration/read", {"projectId": project_id})
files_payload = post("/files/read", {"projectId": project_id, "name": "main.py", "codeSourceId": code_source_id})

result: Dict[str, Any] = {
    "project": project_payload.get("projects", [None])[0],
    "collaboration": {
        "userPermissions": collab_payload.get("userPermissions"),
        "userLiveControl": collab_payload.get("userLiveControl"),
        "collaborators": collab_payload.get("collaborators", []),
    },
    "main_file": None,
    "lock": None,
}

files = files_payload.get("files", [])
if files:
    main_file = files[0]
    result["main_file"] = {
        "name": main_file.get("name"),
        "modified": main_file.get("modified"),
        "open": main_file.get("open"),
        "length": len(main_file.get("content", "")),
        "starts_with": main_file.get("content", "")[:120],
    }

if mode == "acquire-lock":
    lock_payload = post(
        "/projects/collaboration/lock/acquire",
        {"projectId": project_id, "codeSourceId": code_source_id},
    )
    result["lock"] = {
        "codeSourceId": code_source_id,
        "success": lock_payload.get("success"),
        "errors": lock_payload.get("errors", []),
    }

print(json.dumps(result, indent=2, sort_keys=True))
PY
