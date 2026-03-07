#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PY_PATH="$PROJECT_ROOT/lean_workspace/QualityGrowthPi/config.py"
STRATEGY_YAML_PATH="$PROJECT_ROOT/config/strategy.yaml"
APP_YAML_PATH="$PROJECT_ROOT/config/app.yaml"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'python3 is required for LEAN project sync.\n' >&2
  exit 1
fi

if [[ ! -f "$CONFIG_PY_PATH" ]]; then
  printf 'Missing LEAN project config: %s\n' "$CONFIG_PY_PATH" >&2
  exit 1
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - "$CONFIG_PY_PATH" "$STRATEGY_YAML_PATH" "$APP_YAML_PATH" <<'PY'
from pprint import pformat
import sys
from pathlib import Path

import yaml

config_py_path = Path(sys.argv[1])
strategy_yaml_path = Path(sys.argv[2])
app_yaml_path = Path(sys.argv[3])

namespace = {}
exec(config_py_path.read_text(encoding="utf-8"), namespace)
config_payload = dict(namespace.get("CONFIG", {}))
strategy_payload = yaml.safe_load(strategy_yaml_path.read_text(encoding="utf-8")) or {}
app_payload = yaml.safe_load(app_yaml_path.read_text(encoding="utf-8")) or {}

config_payload["strategy"] = strategy_payload.get("strategy", {})
execution = app_payload.get("execution", {})
config_payload["runtime"] = {
    "bootstrap_history_days": int(execution.get("bootstrap_history_days", 35)),
    "stale_data_max_age_minutes": int(execution.get("stale_data_max_age_minutes", 30)),
    "cloud_audit_logging": True,
}

config_py_path.write_text(
    '"""Cloud-safe LEAN project configuration."""\n\nCONFIG = '
    + pformat(config_payload, sort_dicts=False)
    + "\n",
    encoding="utf-8",
)
print(
    "Synchronized LEAN project config: "
    f"bootstrap_history_days={config_payload['runtime']['bootstrap_history_days']}, "
    f"stale_data_max_age_minutes={config_payload['runtime']['stale_data_max_age_minutes']}, "
    f"algorithm={config_payload['strategy'].get('algorithm_name', '')}"
)
PY
