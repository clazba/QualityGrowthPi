"""Basic LEAN workspace integration checks."""

import importlib.util
import sys
from pathlib import Path


def test_quality_growth_pi_config_exists() -> None:
    config_path = Path("lean_workspace/QualityGrowthPi/config.py").resolve()
    spec = importlib.util.spec_from_file_location("qgpi_config", config_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load config module from {config_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["qgpi_config"] = module
    spec.loader.exec_module(module)
    payload = module.CONFIG
    assert payload["algorithm-name"] == "QualityGrowthPi"
    assert payload["strategy-config"].endswith("config/strategy.yaml")
    assert payload["strategy"]["rebalance"]["max_holdings"] == 20
    assert payload["runtime"]["bootstrap_history_days"] >= 30
