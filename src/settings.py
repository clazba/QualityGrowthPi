"""Settings loading, environment expansion, and path resolution."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.models import (
    BacktestConfig,
    ExecutionConfig,
    LLMSettingsModel,
    LocalDataStackConfig,
    PaperTradingConfig,
    PathConfig,
    RuntimeConfig,
    StrategyParameters,
)


ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError("Could not locate project root from pyproject.toml")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), match.group(0)), value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def _resolve_path(base: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def resolve_project_path(path: str | Path, project_root: Path | None = None) -> Path:
    """Resolve a path relative to the repository root when needed."""

    root = _resolve_project_root(project_root)
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else (root / candidate).resolve()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Loaded application settings and resolved filesystem paths."""

    project_root: Path
    runtime_root: Path
    runtime: RuntimeConfig
    paths: PathConfig
    execution: ExecutionConfig
    backtest: BacktestConfig
    paper_trading: PaperTradingConfig
    local_data_stack: LocalDataStackConfig
    strategy: StrategyParameters
    llm: LLMSettingsModel
    state_db_path: Path
    lock_path: Path
    logs_dir: Path
    state_dir: Path
    results_dir: Path
    data_dir: Path
    prompts_dir: Path
    env_path: Path
    log_level: str

    def ensure_directories(self) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "news_cache").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "market_cache").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "llm_cache").mkdir(parents=True, exist_ok=True)


def load_settings(project_root: Path | None = None) -> Settings:
    """Load YAML configuration and overlay environment-derived values."""

    root = _resolve_project_root(project_root)
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    app_payload = _expand_env(_load_yaml(root / "config" / "app.yaml"))
    strategy_payload = _expand_env(_load_yaml(root / "config" / "strategy.yaml"))
    llm_payload = _expand_env(_load_yaml(root / "config" / "llm.yaml"))

    runtime = RuntimeConfig(**app_payload["runtime"])
    paths = PathConfig(**app_payload["paths"])
    execution = ExecutionConfig(**app_payload["execution"])
    backtest = BacktestConfig(**app_payload["backtest"])
    paper_trading = PaperTradingConfig(**app_payload["paper_trading"])
    local_data_stack = LocalDataStackConfig(**app_payload["local_data_stack"])
    strategy = StrategyParameters(**strategy_payload["strategy"])
    llm = LLMSettingsModel(**llm_payload["llm"])

    runtime = RuntimeConfig(
        **{
            **runtime.model_dump(mode="python"),
            "environment": os.getenv("QUANT_GPT_ENV", runtime.environment),
            "provider_mode": os.getenv("QUANT_GPT_PROVIDER_MODE", runtime.provider_mode.value),
            "llm_enabled": _env_bool("QUANT_GPT_ENABLE_LLM", runtime.llm_enabled),
            "llm_mode": os.getenv("QUANT_GPT_LLM_MODE", runtime.llm_mode.value),
        }
    )
    llm = LLMSettingsModel(
        **{
            **llm.model_dump(mode="python"),
            "enabled": _env_bool("QUANT_GPT_ENABLE_LLM", llm.enabled),
            "mode": os.getenv("QUANT_GPT_LLM_MODE", llm.mode.value),
            "default_model": os.getenv("GEMINI_MODEL_ID", llm.default_model).replace(
                "${GEMINI_MODEL_ID}", "gemini-3.1-flash-lite-preview"
            ),
            "fallback_model": os.getenv("GEMINI_FALLBACK_MODEL_ID", llm.fallback_model).replace(
                "${GEMINI_FALLBACK_MODEL_ID}", "gemini-3.1-flash"
            ),
            "timeout_seconds": int(os.getenv("GEMINI_TIMEOUT_SECONDS", str(llm.timeout_seconds))),
            "max_retries": int(os.getenv("GEMINI_MAX_RETRIES", str(llm.max_retries))),
            "cache_ttl_minutes": int(os.getenv("LLM_CACHE_TTL_MINUTES", str(llm.cache_ttl_minutes))),
            "max_symbols_per_batch": int(os.getenv("LLM_MAX_SYMBOLS_PER_BATCH", str(llm.max_symbols_per_batch))),
            "budget_usd_daily": float(os.getenv("LLM_BUDGET_USD_DAILY", str(llm.budget_usd_daily))),
            "estimated_request_cost_usd": float(
                os.getenv("LLM_ESTIMATED_REQUEST_COST_USD", str(llm.estimated_request_cost_usd))
            ),
        }
    )
    backtest = BacktestConfig(
        **{
            **backtest.model_dump(mode="python"),
            "mode": os.getenv("BACKTEST_MODE", backtest.mode.value),
            "project_name": os.getenv("LEAN_BACKTEST_PROJECT", backtest.project_name),
            "push_on_cloud": _env_bool("LEAN_CLOUD_PUSH_ON_BACKTEST", backtest.push_on_cloud),
            "open_results": _env_bool("LEAN_CLOUD_OPEN_RESULTS", backtest.open_results),
        }
    )
    paper_trading = PaperTradingConfig(
        **{
            **paper_trading.model_dump(mode="python"),
            "deployment_target": os.getenv(
                "PAPER_DEPLOYMENT_TARGET",
                paper_trading.deployment_target.value,
            ),
            "broker": os.getenv("PAPER_BROKER", paper_trading.broker.value),
            "environment": os.getenv("PAPER_ENVIRONMENT", paper_trading.environment),
            "live_data_provider": os.getenv("PAPER_LIVE_DATA_PROVIDER", paper_trading.live_data_provider),
            "historical_data_provider": os.getenv(
                "PAPER_HISTORICAL_DATA_PROVIDER",
                paper_trading.historical_data_provider,
            ),
            "push_to_cloud": _env_bool("LEAN_CLOUD_PUSH_ON_PAPER", paper_trading.push_to_cloud),
            "open_results": _env_bool("LEAN_CLOUD_OPEN_PAPER", paper_trading.open_results),
        }
    )
    local_data_stack = LocalDataStackConfig(
        **{
            **local_data_stack.model_dump(mode="python"),
            "fundamentals_provider": os.getenv(
                "LOCAL_FUNDAMENTALS_PROVIDER",
                local_data_stack.fundamentals_provider,
            ),
            "daily_bars_provider": os.getenv(
                "LOCAL_DAILY_BARS_PROVIDER",
                local_data_stack.daily_bars_provider,
            ),
            "news_provider": os.getenv("NEWS_PROVIDER_MODE", local_data_stack.news_provider.value),
        }
    )

    runtime_root = Path(os.getenv("QUANT_GPT_RUNTIME_ROOT", str(root))).expanduser().resolve()
    log_level = os.getenv("QUANT_GPT_LOG_LEVEL", "DEBUG")
    state_db_override = os.getenv("QUANT_GPT_STATE_DB")

    logs_dir = _resolve_path(runtime_root, paths.logs_dir)
    state_dir = _resolve_path(runtime_root, paths.state_dir)
    results_dir = _resolve_path(runtime_root, paths.results_dir)
    data_dir = _resolve_path(runtime_root, paths.data_dir)
    prompts_dir = _resolve_path(root, paths.prompts_dir)

    state_db_path = (
        Path(state_db_override).expanduser().resolve()
        if state_db_override
        else _resolve_path(runtime_root, runtime.state_db)
    )
    lock_path = _resolve_path(runtime_root, runtime.runtime_lock)

    return Settings(
        project_root=root,
        runtime_root=runtime_root,
        runtime=runtime,
        paths=paths,
        execution=execution,
        backtest=backtest,
        paper_trading=paper_trading,
        local_data_stack=local_data_stack,
        strategy=strategy,
        llm=llm,
        state_db_path=state_db_path,
        lock_path=lock_path,
        logs_dir=logs_dir,
        state_dir=state_dir,
        results_dir=results_dir,
        data_dir=data_dir,
        prompts_dir=prompts_dir,
        env_path=env_path,
        log_level=log_level,
    )
