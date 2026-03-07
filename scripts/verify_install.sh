#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
SYSTEM_PYTHON="$(command -v python3 || true)"
PYTHON_BIN="$VENV_PYTHON"
PYTHON_SOURCE=".venv"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$SYSTEM_PYTHON"
  PYTHON_SOURCE="system python3"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  printf 'python3 is not installed and no virtualenv interpreter was found.\n' >&2
  exit 1
fi

printf 'Selected Python (%s): %s\n' "$PYTHON_SOURCE" "$PYTHON_BIN"
"$PYTHON_BIN" --version

if [[ -n "$SYSTEM_PYTHON" ]]; then
  printf 'System python3: %s\n' "$SYSTEM_PYTHON"
  "$SYSTEM_PYTHON" --version
else
  printf 'System python3: not found\n'
fi

if [[ -x "$VENV_PYTHON" ]]; then
  printf 'Virtualenv Python: %s\n' "$VENV_PYTHON"
  "$VENV_PYTHON" --version
else
  printf 'Virtualenv Python: not found\n'
  printf 'Recommendation: run ./scripts/bootstrap_pi.sh to create .venv and install dependencies.\n'
fi

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required for verification; install Python 3.11 on the target host.")
PY

if ! "$PYTHON_BIN" - <<'PY'
import importlib.util
import sys

required = [
    "pytest",
    "yaml",
    "dotenv",
    "pydantic",
    "jsonschema",
    "numpy",
    "requests",
]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    print("Missing Python packages for selected interpreter: " + ", ".join(sorted(missing)))
    sys.exit(1)
PY
then
  printf 'Project Python dependencies are not installed for %s.\n' "$PYTHON_BIN" >&2
  printf 'Recommended fix:\n' >&2
  printf '  1. cd %s\n' "$PROJECT_ROOT" >&2
  printf '  2. ./scripts/bootstrap_pi.sh\n' >&2
  printf 'Or manually:\n' >&2
  printf '  1. python3 -m venv .venv\n' >&2
  printf '  2. . .venv/bin/activate\n' >&2
  printf '  3. python -m pip install --upgrade pip wheel\n' >&2
  printf '  4. python -m pip install -r requirements.txt\n' >&2
  exit 1
fi

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
cd "$PROJECT_ROOT"
find "$PROJECT_ROOT/src" "$PROJECT_ROOT/tests" "$PROJECT_ROOT/lean_workspace/QualityGrowthPi" \
  -type f -name '*.py' ! -name '._*' -print0 | xargs -0 "$PYTHON_BIN" -m py_compile
"$PYTHON_BIN" -m pytest --collect-only -q "$PROJECT_ROOT/tests" "$PROJECT_ROOT/lean_workspace/QualityGrowthPi/tests" --ignore-glob='**/._*'
bash -n "$PROJECT_ROOT"/scripts/*.sh

printf 'Verification completed successfully\n'
