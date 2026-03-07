#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEAN_JSON_PATH="$PROJECT_ROOT/lean_workspace/lean.json"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ ! -f "$LEAN_JSON_PATH" ]]; then
  printf 'Missing LEAN workspace config: %s\n' "$LEAN_JSON_PATH" >&2
  exit 1
fi

resolve_env_value() {
  local key="$1"
  python3 - "$ENV_FILE" "$key" <<'PY'
import os
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
key = sys.argv[2]

value = os.environ.get(key, "")
if value:
    print(value)
    raise SystemExit(0)

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
        quote = rhs[0]
        body = rhs[1:-1]
        if quote == "'":
            body = body.replace("'\"'\"'", "'")
        print(body)
    else:
        print(rhs)
    break
PY
}

LEAN_ORGANIZATION_ID="${LEAN_ORGANIZATION_ID:-$(resolve_env_value "LEAN_ORGANIZATION_ID")}"
LEAN_DATA_DIRECTORY="${LEAN_DATA_DIRECTORY:-$(resolve_env_value "LEAN_DATA_DIRECTORY")}"

if [[ -z "$LEAN_ORGANIZATION_ID" ]]; then
  printf 'LEAN organization id is not set.\n' >&2
  printf 'Set LEAN_ORGANIZATION_ID in %s or export it in the current shell.\n' "$ENV_FILE" >&2
  printf 'Without it, commands such as "lean data download" will fail with "Organization not found".\n' >&2
  exit 1
fi

if [[ "$LEAN_ORGANIZATION_ID" =~ [[:space:]] ]]; then
  printf 'LEAN_ORGANIZATION_ID looks incorrect: %s\n' "$LEAN_ORGANIZATION_ID" >&2
  printf 'This field should be the QuantConnect organization id stored in lean.json, not a display name.\n' >&2
  printf 'Example shape: 32-character hex-like id.\n' >&2
  exit 1
fi

python3 - "$LEAN_JSON_PATH" "$LEAN_ORGANIZATION_ID" "$LEAN_DATA_DIRECTORY" <<'PY'
import json
import sys
from pathlib import Path

lean_json_path = Path(sys.argv[1])
organization_id = sys.argv[2]
data_directory = sys.argv[3]

payload = json.loads(lean_json_path.read_text(encoding="utf-8"))
payload["job-organization-id"] = organization_id
if data_directory:
    payload["data-folder"] = data_directory

lean_json_path.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")
print(f'Synchronized LEAN workspace config: organization={organization_id}, data-folder={payload["data-folder"]}')
PY
