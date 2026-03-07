#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
PROJECT_DIR="$PROJECT_ROOT/lean_workspace/QualityGrowthPi"

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
  printf 'python3 is required for QuantConnect cloud file sync.\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - "$PROJECT_DIR" <<'PY'
from __future__ import annotations

import json
import os
import sys
from base64 import b64encode
from hashlib import sha256
from pathlib import Path
from time import time
from typing import Any, Dict, List

import requests

BASE_URL = "https://www.quantconnect.com/api/v2"
LOCAL_FILES = ("main.py", "scoring.py", "config.py")

project_dir = Path(sys.argv[1]).resolve()
project_id_raw = os.getenv("LEAN_BACKTEST_PROJECT_ID", "").strip()
user_id = os.getenv("QUANTCONNECT_USER_ID", "").strip()
api_token = os.getenv("QUANTCONNECT_API_TOKEN", "").strip()
code_source_id = os.getenv("QC_CODE_SOURCE_ID", "quant_gpt_cli").strip() or "quant_gpt_cli"

if not project_id_raw:
    raise SystemExit("LEAN_BACKTEST_PROJECT_ID is required for QuantConnect cloud file sync.")
if not user_id or not api_token:
    raise SystemExit("QUANTCONNECT_USER_ID and QUANTCONNECT_API_TOKEN are required for QuantConnect cloud file sync.")

project_id = int(project_id_raw)


def get_headers() -> Dict[str, str]:
    timestamp = f"{int(time())}"
    hashed_token = sha256(f"{api_token}:{timestamp}".encode("utf-8")).hexdigest()
    authentication = b64encode(f"{user_id}:{hashed_token}".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {authentication}",
        "Timestamp": timestamp,
    }


def post(endpoint: str, payload: Dict[str, object]) -> Dict[str, object]:
    response = requests.post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload, timeout=30)
    response.raise_for_status()
    decoded = response.json()
    if not decoded.get("success", False):
        raise RuntimeError(f"{endpoint} failed: {decoded.get('errors')}")
    return decoded


post(
    "/projects/collaboration/lock/acquire",
    {"projectId": project_id, "codeSourceId": code_source_id},
)

existing_files_payload = post(
    "/files/read",
    {"projectId": project_id, "codeSourceId": code_source_id},
)
existing_names = {str(item["name"]) for item in existing_files_payload.get("files", [])}
uploaded: List[Dict[str, object]] = []

for filename in LOCAL_FILES:
    local_path = project_dir / filename
    if not local_path.exists():
        raise SystemExit(f"Missing local LEAN project file: {local_path}")
    content = local_path.read_text(encoding="utf-8")
    payload = {
        "projectId": project_id,
        "name": filename,
        "content": content,
        "codeSourceId": code_source_id,
    }
    endpoint = "/files/update" if filename in existing_names else "/files/create"
    post(endpoint, payload)
    verification = post(
        "/files/read",
        {"projectId": project_id, "name": filename, "codeSourceId": code_source_id},
    )
    files = verification.get("files", [])
    if not files:
        raise RuntimeError(f"Verification failed: QuantConnect returned no file payload for {filename}")
    cloud_file = files[0]
    cloud_content = str(cloud_file.get("content", ""))
    uploaded.append(
        {
            "name": filename,
            "local_length": len(content),
            "cloud_length": len(cloud_content),
            "cloud_modified": cloud_file.get("modified"),
        }
    )
    if len(cloud_content) == 0:
        raise RuntimeError(
            f"QuantConnect cloud file {filename} is still empty after {endpoint}. "
            f"local_length={len(content)} codeSourceId={code_source_id}"
        )

verification = post(
    "/files/read",
    {"projectId": project_id, "codeSourceId": code_source_id},
)
verified = sorted(str(item["name"]) for item in verification.get("files", []))
print(
    json.dumps(
        {
            "code_source_id": code_source_id,
            "project_id": project_id,
            "synced_files": list(LOCAL_FILES),
            "uploaded": uploaded,
            "cloud_files": verified,
        },
        indent=2,
        sort_keys=True,
    )
)
PY
