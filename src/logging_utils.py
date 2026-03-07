"""Logging configuration helpers."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

import yaml

from src.settings import Settings


def _load_logging_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def configure_logging(settings: Settings) -> None:
    """Configure structured operator, audit, and LLM logging."""

    settings.ensure_directories()
    config = _load_logging_config(settings.project_root / "config" / "logging.yaml")

    handlers = config.get("handlers", {})
    for handler in handlers.values():
        filename = handler.get("filename")
        if not filename:
            continue
        file_path = Path(filename)
        if not file_path.is_absolute():
            file_path = settings.runtime_root / file_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        handler["filename"] = str(file_path)
        if handler.get("level") == "DEBUG":
            handler["level"] = settings.log_level

    for logger_name in ("quant_gpt", "quant_gpt.llm"):
        if logger_name in config.get("loggers", {}):
            config["loggers"][logger_name]["level"] = settings.log_level

    logging.config.dictConfig(config)


def get_logger(name: str = "quant_gpt") -> logging.Logger:
    """Return a configured logger."""

    return logging.getLogger(name)
