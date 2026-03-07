"""SEC EDGAR fundamentals adapter using normalized local snapshot caches."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models import FundamentalSnapshot
from src.provider_adapters.base import MarketDataProvider, ProviderError


class SECFundamentalsAdapter(MarketDataProvider):
    """SEC-based fundamentals adapter driven by normalized local snapshot caches."""

    def __init__(self, fundamentals_cache_path: Path | None = None) -> None:
        self.fundamentals_cache_path = fundamentals_cache_path or Path(
            os.getenv(
                "SEC_FUNDAMENTALS_CACHE_PATH",
                str(Path.cwd() / "data" / "market_cache" / "sec" / "fundamentals_snapshot.jsonl"),
            )
        )
        self.user_agent = os.getenv("SEC_API_USER_AGENT", "").strip()

    def provider_name(self) -> str:
        return "sec"

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def build_snapshot_from_normalized_record(cls, record: dict[str, Any]) -> FundamentalSnapshot:
        """Build a snapshot from a pre-normalized SEC cache record."""

        return FundamentalSnapshot(
            symbol=str(record["symbol"]),
            as_of=datetime.fromisoformat(record["as_of"]) if record.get("as_of") else None,
            has_fundamental_data=bool(record.get("has_fundamental_data", True)),
            market_cap=float(record["market_cap"]),
            exchange_id=str(record.get("exchange_id", "NYS")),
            price=float(record["price"]),
            volume=float(record["volume"]),
            roe=cls._coerce_float(record.get("roe")),
            gross_margin=cls._coerce_float(record.get("gross_margin")),
            debt_to_equity=cls._coerce_float(record.get("debt_to_equity")),
            revenue_growth=cls._coerce_float(record.get("revenue_growth")),
            net_income_growth=cls._coerce_float(record.get("net_income_growth")),
            pe_ratio=cls._coerce_float(record.get("pe_ratio")),
            peg_ratio=cls._coerce_float(record.get("peg_ratio")),
        )

    def fetch_fundamentals(self, as_of: datetime | None = None) -> list[FundamentalSnapshot]:
        if not self.fundamentals_cache_path.exists():
            raise ProviderError(
                f"SEC fundamentals cache not found: {self.fundamentals_cache_path}. "
                "Populate a normalized snapshot cache built from EDGAR companyfacts/submissions before using SEC in the local stack."
            )
        snapshots: list[FundamentalSnapshot] = []
        with self.fundamentals_cache_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                snapshot = self.build_snapshot_from_normalized_record(json.loads(line))
                if as_of and snapshot.as_of and snapshot.as_of > as_of:
                    continue
                snapshots.append(snapshot)
        return snapshots

    def fetch_daily_bars(self, symbol: str, lookback_days: int):  # type: ignore[override]
        raise ProviderError(
            "SEC does not provide price/volume bars. Pair SECFundamentalsAdapter with Alpaca, Massive, or Alpha Vantage for daily bars."
        )
