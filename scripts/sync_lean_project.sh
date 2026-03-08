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
CONFIG_PY_PATH="$PROJECT_ROOT/lean_workspace/$LEAN_PROJECT_NAME/config.py"

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
"$PYTHON_BIN" - "$CONFIG_PY_PATH" <<'PY'
import os
from pprint import pformat
import sys
from pathlib import Path

from src.strategy_settings import (
    build_quality_growth_payload,
    build_runtime_payload,
    build_stat_arb_payload,
)

config_py_path = Path(sys.argv[1])

namespace = {}
exec(config_py_path.read_text(encoding="utf-8"), namespace)
config_payload = dict(namespace.get("CONFIG", {}))
project_root = config_py_path.parents[2]
profile = os.getenv("QUANT_GPT_SETTINGS_PROFILE", "default")
strategy_mode = os.getenv("QUANT_GPT_STRATEGY_MODE", "quality_growth").strip().lower()
project_name = config_py_path.parent.name
if project_name == "GraphStatArb" or strategy_mode == "stat_arb_graph_pairs":
    strategy_payload = build_stat_arb_payload(profile)
    runtime_payload = build_runtime_payload(profile, "stat_arb_graph_pairs")
else:
    strategy_payload = build_quality_growth_payload(profile)
    runtime_payload = build_runtime_payload(profile, "quality_growth")
config_payload["algorithm-name"] = strategy_payload["algorithm_name"]
config_payload["project-root"] = str(project_root)
config_payload["shared-module-root"] = str((project_root / "src").resolve())
config_payload["strategy-config"] = str((project_root / "src" / "strategy_settings.py").resolve())
config_payload["app-config"] = str((project_root / "config" / "app.yaml").resolve())
config_payload["settings-profile"] = profile
config_payload["strategy"] = strategy_payload
config_payload["runtime"] = runtime_payload
config_payload["notes"] = [
    "src/strategy_settings.py is the single source of truth for parameters that move backtest outputs.",
    "The LEAN cloud entrypoint is intentionally self-contained and does not rely on repo-level Python packages.",
    "Use scripts/sync_lean_project.sh after changing strategy settings or QUANT_GPT_SETTINGS_PROFILE.",
]

config_py_path.write_text(
    '"""Cloud-safe LEAN project configuration."""\n\nCONFIG = '
    + pformat(config_payload, sort_dicts=False)
    + "\n",
    encoding="utf-8",
)
print(
    "Synchronized LEAN project config: "
    f"project={project_name}, "
    f"strategy_mode={strategy_mode}, "
    f"profile={profile}, "
    f"backtest_start_date={config_payload['runtime']['backtest_start_date']}, "
    f"initial_cash={config_payload['runtime']['initial_cash']}, "
    f"bootstrap_history_days={config_payload['runtime']['bootstrap_history_days']}, "
    f"stale_data_max_age_minutes={config_payload['runtime']['stale_data_max_age_minutes']}, "
    f"fine_universe_limit={config_payload['runtime']['fine_universe_limit']}, "
    f"algorithm={config_payload['strategy'].get('algorithm_name', '')}"
)
PY
