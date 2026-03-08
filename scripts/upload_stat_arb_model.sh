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

ARTIFACT_PATH="${1:-${STAT_ARB_LOCAL_MODEL_PATH:-}}"
OBJECT_STORE_KEY="${2:-${STAT_ARB_OBJECT_STORE_MODEL_KEY:-}}"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'python3 is required to validate the stat-arb model artifact.\n' >&2
  exit 1
fi

if [[ -z "${ARTIFACT_PATH:-}" ]]; then
  printf 'Provide the model artifact path as the first argument or set STAT_ARB_LOCAL_MODEL_PATH in .env.\n' >&2
  exit 1
fi

if [[ -z "${OBJECT_STORE_KEY:-}" ]]; then
  printf 'Provide the Object Store key as the second argument or set STAT_ARB_OBJECT_STORE_MODEL_KEY in .env.\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - "$ARTIFACT_PATH" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from src.stat_arb.model_loader import load_model_artifact_from_path

artifact_path = Path(sys.argv[1]).expanduser().resolve()
expected_schema_version = os.getenv("STAT_ARB_FEATURE_SCHEMA_VERSION", "stat_arb_v1").strip() or "stat_arb_v1"
expected_model_version = os.getenv("STAT_ARB_ML_MODEL_VERSION", "ensemble_v1").strip() or "ensemble_v1"

artifact = load_model_artifact_from_path(
    artifact_path,
    expected_schema_version=expected_schema_version,
    expected_model_version=expected_model_version,
)
print(
    json.dumps(
        {
            "artifact_path": str(artifact_path),
            "schema_version": artifact.schema_version,
            "model_version": artifact.model_version,
            "feature_names": list(artifact.feature_names),
            "has_global_feature_importance": bool(artifact.global_feature_importance),
            "training_metadata_keys": sorted(artifact.training_metadata),
        },
        indent=2,
        sort_keys=True,
    )
)
PY

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is required to upload the stat-arb model to QuantConnect Object Store.\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT/lean_workspace"
lean cloud object-store set "$OBJECT_STORE_KEY" "$ARTIFACT_PATH"
printf 'Uploaded stat-arb model artifact to Object Store key: %s\n' "$OBJECT_STORE_KEY"
