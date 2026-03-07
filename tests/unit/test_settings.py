"""Unit tests for settings resolution."""

from pathlib import Path

from src.settings import load_settings


def test_runtime_root_can_be_overridden(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QUANT_GPT_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_GPT_STATE_DB", str(tmp_path / "state" / "override.db"))
    settings = load_settings()
    assert settings.runtime_root == tmp_path.resolve()
    assert settings.state_db_path == (tmp_path / "state" / "override.db").resolve()
