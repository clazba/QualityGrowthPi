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
