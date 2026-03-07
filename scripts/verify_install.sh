#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

printf 'Using Python: %s\n' "$PYTHON_BIN"
"$PYTHON_BIN" --version

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required for verification; install Python 3.11 on the target host.")
PY

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  printf '.env present: yes\n'
else
  printf '.env present: no (run make env)\n'
fi

if command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI: %s\n' "$(command -v lean)"
else
  printf 'LEAN CLI: not installed\n'
fi

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$PROJECT_ROOT"/scripts/*.sh
else
  printf 'shellcheck not installed; skipping shell lint\n'
fi

export PYTHONPYCACHEPREFIX="$PROJECT_ROOT/.pycache"
find "$PROJECT_ROOT/src" "$PROJECT_ROOT/tests" "$PROJECT_ROOT/lean_workspace/QualityGrowthPi" \
  -type f -name '*.py' ! -name '._*' -print0 | xargs -0 "$PYTHON_BIN" -m py_compile
"$PYTHON_BIN" -m pytest --collect-only -q "$PROJECT_ROOT/tests" "$PROJECT_ROOT/lean_workspace/QualityGrowthPi/tests" --ignore-glob='**/._*'
bash -n "$PROJECT_ROOT"/scripts/*.sh

printf 'Verification completed successfully\n'
