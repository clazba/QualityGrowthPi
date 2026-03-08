#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN=""

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]] && "$PROJECT_ROOT/.venv/bin/python" -c 'import sys' >/dev/null 2>&1; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'python3 is required to run tests.\n' >&2
  exit 1
fi

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import importlib
import sys

if sys.version_info < (3, 11):
    raise SystemExit(1)

for module_name in ("pytest", "yaml", "pydantic", "dotenv", "requests", "jsonschema", "numpy", "joblib", "sklearn"):
    importlib.import_module(module_name)
PY
then
  printf 'The selected Python environment is not compatible for this test suite.\n' >&2
  printf 'Selected interpreter: %s\n' "$PYTHON_BIN" >&2
  printf 'Requirements: Python 3.11+ with pytest, PyYAML, pydantic, python-dotenv, requests, jsonschema, and numpy installed.\n' >&2
  printf 'On the Pi, run tests from the project venv:\n' >&2
  printf '  cd /mnt/nvme_data/shared/quant_gpt && ./scripts/run_tests.sh\n' >&2
  printf 'On this Mac, create a local Python 3.11+ environment first if you want to run the suite here.\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" -m pytest \
  "$PROJECT_ROOT/tests" \
  "$PROJECT_ROOT/lean_workspace/QualityGrowthPi/tests" \
  "$PROJECT_ROOT/lean_workspace/GraphStatArb/tests"
