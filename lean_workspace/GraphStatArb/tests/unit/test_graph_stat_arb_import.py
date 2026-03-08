"""LEAN workspace coverage for the graph stat-arb project."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path("lean_workspace/GraphStatArb").resolve()


def _load_module(module_name: str, relative_path: str):
    module_path = (PROJECT_DIR / relative_path).resolve()
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_graph_stat_arb_entrypoint_exposes_qcalgorithm_subclass() -> None:
    main_module = _load_module("graph_stat_arb_main", "main.py")
    algorithm_cls = getattr(main_module, "GraphStatArbAlgorithm")
    base_cls = getattr(main_module, "QCAlgorithm")
    assert issubclass(algorithm_cls, base_cls)


def test_graph_stat_arb_cycle_generates_cluster_and_pair_intent() -> None:
    stat_arb = _load_module("graph_stat_arb_module", "stat_arb.py")
    config = stat_arb.load_strategy_config(PROJECT_DIR / "config.py")
    as_of = datetime.now(stat_arb.UTC)
    price_history = {
        "AAPL": [100, 101, 102, 103, 104, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 105],
        "MSFT": [200, 202, 204, 206, 208, 204, 202, 200, 198, 196, 198, 200, 202, 204, 206, 208, 206, 204, 202, 200, 198, 196, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 210, 208, 206, 204, 202, 200, 198, 196, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 210, 208, 206, 204, 202, 200, 198, 196, 198, 200, 202, 204, 206, 208, 210],
        "NVDA": [50, 51, 52, 53, 54, 53, 52, 51, 50, 49, 50, 51, 52, 53, 54, 55, 54, 53, 52, 51, 50, 49, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 56, 55, 54, 53, 52, 51, 50, 49, 50, 51, 52, 53, 54, 55, 56],
        "AVGO": [80, 81, 82, 83, 84, 83, 82, 81, 80, 79, 80, 81, 82, 83, 84, 85, 84, 83, 82, 81, 80, 79, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 86, 85, 84, 83, 82, 81, 80, 79, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 86, 85, 84, 83, 82, 81, 80, 79, 80, 81, 82, 83, 84, 85, 86],
    }
    cycle = stat_arb.run_stat_arb_cycle(config, price_history, as_of, 100000.0, [])

    assert cycle.clusters
    assert cycle.candidates
    assert cycle.decisions


def test_graph_stat_arb_filter_falls_back_when_object_store_key_is_missing() -> None:
    stat_arb = _load_module("graph_stat_arb_filter_missing", "stat_arb.py")
    config = stat_arb.load_strategy_config(PROJECT_DIR / "config.py")
    config["strategy"]["ml_filter"]["mode"] = "object_store_model"
    config["strategy"]["ml_filter"]["model_version"] = "ensemble_v2"
    config["strategy"]["ml_filter"]["object_store_model_key"] = "stat-arb/models/ensemble_v2/ensemble.joblib"
    config["strategy"]["ml_filter"]["local_model_path"] = ""

    class FakeObjectStore:
        def ContainsKey(self, key):  # noqa: N802
            return False

        def ReadBytes(self, key):  # noqa: N802
            return b""

    scorer, status = stat_arb.build_trade_filter(config, object_store=FakeObjectStore())
    candidate = stat_arb.run_stat_arb_cycle(
        config,
        {
            "AAPL": [100, 101, 102, 103, 104, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 105],
            "MSFT": [200, 202, 204, 206, 208, 204, 202, 200, 198, 196, 198, 200, 202, 204, 206, 208, 206, 204, 202, 200, 198, 196, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 210, 208, 206, 204, 202, 200, 198, 196, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 210, 208, 206, 204, 202, 200, 198, 196, 198, 200, 202, 204, 206, 208, 210],
        },
        datetime.now(stat_arb.UTC),
        100000.0,
        [],
        trade_filter=scorer,
    )

    assert status.fallback_active is True
    assert status.active_mode == "embedded_scorecard"
    assert candidate.ml_filter_status["fallback_active"] is True


def test_graph_stat_arb_filter_uses_loaded_artifact_when_available() -> None:
    stat_arb = _load_module("graph_stat_arb_filter_loaded", "stat_arb.py")
    config = stat_arb.load_strategy_config(PROJECT_DIR / "config.py")
    config["strategy"]["ml_filter"]["mode"] = "object_store_model"
    config["strategy"]["ml_filter"]["model_version"] = "ensemble_v2"
    config["strategy"]["ml_filter"]["object_store_model_key"] = "stat-arb/models/ensemble_v2/ensemble.joblib"
    config["strategy"]["ml_filter"]["local_model_path"] = ""

    class FakePipeline:
        def predict_proba(self, rows):
            assert len(rows) == 1
            return [[0.2, 0.8]]

    artifact = stat_arb.LoadedModelArtifact(
        schema_version="stat_arb_v1",
        model_version="ensemble_v2",
        feature_names=stat_arb.STAT_ARB_FEATURE_NAMES,
        pipeline=FakePipeline(),
        global_feature_importance={"expected_edge_bps_norm": 0.5},
    )

    stat_arb.load_model_artifact_from_object_store = lambda *args, **kwargs: artifact

    class FakeObjectStore:
        def ContainsKey(self, key):  # noqa: N802
            return True

        def ReadBytes(self, key):  # noqa: N802
            return b"unused"

    scorer, status = stat_arb.build_trade_filter(config, object_store=FakeObjectStore())
    cycle = stat_arb.run_stat_arb_cycle(
        config,
        {
            "AAPL": [100, 101, 102, 103, 104, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 105],
            "MSFT": [200, 202, 204, 206, 208, 204, 202, 200, 198, 196, 198, 200, 202, 204, 206, 208, 206, 204, 202, 200, 198, 196, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 210, 208, 206, 204, 202, 200, 198, 196, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 210, 208, 206, 204, 202, 200, 198, 196, 198, 200, 202, 204, 206, 208, 210],
        },
        datetime.now(stat_arb.UTC),
        100000.0,
        [],
        trade_filter=scorer,
    )

    first_decision = next(iter(cycle.decisions.values()))
    assert status.active_mode == "object_store_model"
    assert cycle.ml_filter_status["active_mode"] == "object_store_model"
    assert first_decision.model_version == "ensemble_v2"
    assert first_decision.metadata["fallback_active"] is False
