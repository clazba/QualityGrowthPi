"""Regression placeholder that validates the workspace manifest structure."""

import json
from pathlib import Path


def test_baseline_manifest_structure() -> None:
    manifest_path = Path("lean_workspace/QualityGrowthPi/tests/regression/baseline_manifest.json")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "expected_artifacts" in payload
    assert "target_weights" in payload["expected_artifacts"]
    assert "cloud_baseline_bundles" in payload["expected_artifacts"]
    assert isinstance(payload.get("captured_baselines", []), list)
