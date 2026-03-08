"""Unit tests for settings resolution."""

from pathlib import Path

from src.settings import load_settings


def test_runtime_root_can_be_overridden(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QUANT_GPT_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_GPT_STATE_DB", str(tmp_path / "state" / "override.db"))
    settings = load_settings()
    assert settings.runtime_root == tmp_path.resolve()
    assert settings.state_db_path == (tmp_path / "state" / "override.db").resolve()


def test_default_provider_plan_matches_repo_decision(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_GPT_PROVIDER_MODE", "external_equivalent")
    monkeypatch.setenv("NEWS_PROVIDER_MODE", "composite")
    monkeypatch.setenv("BACKTEST_MODE", "cloud")
    monkeypatch.setenv("PAPER_DEPLOYMENT_TARGET", "cloud")
    monkeypatch.setenv("PAPER_BROKER", "alpaca")
    monkeypatch.setenv("LOCAL_FUNDAMENTALS_PROVIDER", "massive_sec_alpha_vantage")
    monkeypatch.setenv("LOCAL_DAILY_BARS_PROVIDER", "alpaca")
    settings = load_settings()
    assert settings.backtest.mode.value == "cloud"
    assert settings.paper_trading.deployment_target.value == "cloud"
    assert settings.paper_trading.broker.value == "alpaca"
    assert settings.local_data_stack.fundamentals_provider == "massive_sec_alpha_vantage"
    assert settings.local_data_stack.daily_bars_provider == "alpaca"
    assert settings.local_data_stack.news_provider.value == "composite"


def test_strategy_mode_can_switch_to_stat_arb(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_GPT_STRATEGY_MODE", "stat_arb_graph_pairs")
    settings = load_settings()

    assert settings.runtime.strategy_mode.value == "stat_arb_graph_pairs"
    assert settings.stat_arb.algorithm_name == "GraphStatArb"
    assert settings.backtest.project_name == "GraphStatArb"


def test_stat_arb_ml_filter_env_overrides_are_applied(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_GPT_STRATEGY_MODE", "stat_arb_graph_pairs")
    monkeypatch.setenv("STAT_ARB_ML_FILTER_MODE", "object_store_model")
    monkeypatch.setenv("STAT_ARB_ML_MODEL_VERSION", "ensemble_v2")
    monkeypatch.setenv("STAT_ARB_OBJECT_STORE_MODEL_KEY", "stat-arb/models/ensemble_v2/ensemble.joblib")
    monkeypatch.setenv("STAT_ARB_LOCAL_MODEL_PATH", "/tmp/ensemble_v2.joblib")
    monkeypatch.setenv("STAT_ARB_FEATURE_SCHEMA_VERSION", "stat_arb_v1")

    settings = load_settings()

    assert settings.stat_arb.ml_filter.mode.value == "object_store_model"
    assert settings.stat_arb.ml_filter.model_version == "ensemble_v2"
    assert settings.stat_arb.ml_filter.object_store_model_key == "stat-arb/models/ensemble_v2/ensemble.joblib"
    assert settings.stat_arb.ml_filter.local_model_path == "/tmp/ensemble_v2.joblib"
