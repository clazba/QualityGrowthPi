"""Runtime health helpers, stale data checks, and lock handling."""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.logging_utils import get_logger
from src.settings import Settings


class RuntimeLockError(RuntimeError):
    """Raised when a runtime lock cannot be acquired."""


class RuntimeLock(AbstractContextManager["RuntimeLock"]):
    """Simple PID lock to avoid duplicate local launches."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self.fd: int | None = None

    def __enter__(self) -> "RuntimeLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            owner = self.lock_path.read_text(encoding="utf-8").strip() if self.lock_path.exists() else "unknown"
            raise RuntimeLockError(f"runtime lock already held by {owner}") from exc
        os.write(self.fd, str(os.getpid()).encode("utf-8"))
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.lock_path.exists():
            self.lock_path.unlink()
        return None


@dataclass(frozen=True)
class Heartbeat:
    """Health heartbeat payload."""

    ts: datetime
    environment: str
    provider_mode: str
    llm_mode: str


def stale_data_detected(
    last_updated: datetime | None,
    max_age_minutes: int,
    now: datetime | None = None,
) -> bool:
    """Return True when data is missing or older than the allowed freshness window."""

    if last_updated is None:
        return True
    reference = now or datetime.now(UTC)
    return last_updated < reference - timedelta(minutes=max_age_minutes)


def build_startup_banner(settings: Settings) -> str:
    """Return a concise startup banner for operator logs."""

    return (
        f"QualityGrowthPi | env={settings.runtime.environment} "
        f"| provider={settings.runtime.provider_mode.value} "
        f"| backtest={settings.backtest.mode.value} "
        f"| paper_broker={settings.paper_trading.broker.value} "
        f"| llm_mode={settings.runtime.llm_mode.value} "
        f"| runtime_root={settings.runtime_root}"
    )


def emit_heartbeat(settings: Settings) -> Heartbeat:
    """Log and return a runtime heartbeat."""

    heartbeat = Heartbeat(
        ts=datetime.now(UTC),
        environment=settings.runtime.environment,
        provider_mode=settings.runtime.provider_mode.value,
        llm_mode=settings.runtime.llm_mode.value,
    )
    logger = get_logger("quant_gpt")
    logger.info(
        "heartbeat ts=%s provider=%s llm_mode=%s",
        heartbeat.ts.isoformat(),
        heartbeat.provider_mode,
        heartbeat.llm_mode,
    )
    return heartbeat
