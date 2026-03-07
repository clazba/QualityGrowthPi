"""Abstract interfaces for market data, execution, news, and LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from src.models import FundamentalSnapshot, NewsEvent


class ProviderError(RuntimeError):
    """Raised when a provider cannot satisfy a request safely."""


class MarketDataProvider(ABC):
    """Abstract market data provider interface."""

    @abstractmethod
    def provider_name(self) -> str:
        """Return the adapter name."""

    @abstractmethod
    def fetch_fundamentals(self, as_of: datetime | None = None) -> list[FundamentalSnapshot]:
        """Return point-in-time fundamentals."""

    @abstractmethod
    def fetch_daily_bars(self, symbol: str, lookback_days: int) -> dict[str, list[float]]:
        """Return close and volume history keyed as `closes` and `volumes`."""


class ExecutionProvider(ABC):
    """Abstract execution provider interface."""

    @abstractmethod
    def provider_name(self) -> str:
        """Return the adapter name."""

    @abstractmethod
    def validate(self, paper: bool = True) -> None:
        """Validate connectivity and permissions."""

    @abstractmethod
    def submit_target_weights(self, targets: dict[str, float], paper: bool = True) -> dict[str, Any]:
        """Submit a batch of target weights."""


class NewsProvider(ABC):
    """Abstract news ingestion interface."""

    @abstractmethod
    def provider_name(self) -> str:
        """Return the adapter name."""

    @abstractmethod
    def fetch_news(self, symbols: list[str], since: datetime | None = None) -> list[NewsEvent]:
        """Return curated news items for the supplied symbols."""


class LLMProvider(ABC):
    """Abstract structured JSON generation interface."""

    @abstractmethod
    def provider_name(self) -> str:
        """Return the adapter name."""

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        system_prompt: str,
        schema: dict[str, Any],
        model_name: str,
    ) -> dict[str, Any]:
        """Return schema-shaped JSON output or raise ProviderError."""
