"""Regression placeholder that validates the stat-arb baseline manifest structure."""

import json
from pathlib import Path


def test_graph_stat_arb_baseline_manifest_structure() -> None:
    manifest_path = Path("lean_workspace/GraphStatArb/tests/regression/baseline_manifest.json")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "expected_artifacts" in payload
    assert "pair_trade_intents" in payload["expected_artifacts"]
    assert "cloud_baseline_bundles" in payload["expected_artifacts"]
    assert isinstance(payload.get("captured_baselines", []), list)
