"""Basic LEAN workspace integration checks."""

import json
from pathlib import Path


def test_quality_growth_pi_config_exists() -> None:
    config_path = Path("lean_workspace/QualityGrowthPi/config.json")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["algorithm-name"] == "QualityGrowthPi"
    assert payload["strategy-config"].endswith("config/strategy.yaml")
