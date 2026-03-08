"""Basic LEAN workspace integration checks for the graph stat-arb project."""

import importlib.util
import sys
from pathlib import Path


def test_graph_stat_arb_config_exists() -> None:
    config_path = Path("lean_workspace/GraphStatArb/config.py").resolve()
    spec = importlib.util.spec_from_file_location("graph_stat_arb_config", config_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load config module from {config_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["graph_stat_arb_config"] = module
    spec.loader.exec_module(module)
    payload = module.CONFIG
    assert payload["algorithm-name"] == "GraphStatArb"
    assert payload["strategy-config"].endswith("src/strategy_settings.py")
    assert payload["settings-profile"] == "default"
    assert payload["strategy"]["universe"]["symbols"]
    assert payload["strategy"]["ml_filter"]["mode"] == "embedded_scorecard"
    assert payload["strategy"]["ml_filter"]["feature_schema_version"] == "stat_arb_v1"
    assert payload["runtime"]["backtest_start_date"] == "2022-01-01"
    assert payload["runtime"]["initial_cash"] == 100000.0
    assert payload["runtime"]["bootstrap_history_days"] >= 60
