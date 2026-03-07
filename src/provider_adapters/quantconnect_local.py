"""QuantConnect local-compatible adapter scaffold."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.models import FundamentalSnapshot
from src.provider_adapters.base import MarketDataProvider, ProviderError


class QuantConnectLocalAdapter(MarketDataProvider):
    """Adapter placeholder for locally licensed LEAN-compatible data."""

    def __init__(self, data_directory: Path) -> None:
        self.data_directory = data_directory

    def provider_name(self) -> str:
        return "quantconnect_local"

    def fetch_fundamentals(self, as_of: datetime | None = None) -> list[FundamentalSnapshot]:
        if not self.data_directory.exists():
            raise ProviderError(
                f"LEAN data directory does not exist: {self.data_directory}. "
                "Supply licensed local data before using quantconnect_local mode."
            )
        raise ProviderError(
            "QuantConnect local data parsing is dataset-specific and must be completed against the operator's "
            "licensed local data layout. The provider abstraction is in place; use regression fixtures until "
            "the local dataset mapping is validated."
        )

    def fetch_daily_bars(self, symbol: str, lookback_days: int) -> dict[str, list[float]]:
        if not self.data_directory.exists():
            raise ProviderError(f"LEAN data directory does not exist: {self.data_directory}")
        raise ProviderError(
            "Daily bar loading for local LEAN data is not yet implemented in this scaffold. "
            "Use LEAN backtests for engine-driven execution and compare artefacts via the regression suite."
        )
