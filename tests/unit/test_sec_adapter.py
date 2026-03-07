"""Unit tests for SEC fundamentals cache normalization."""

import json
from datetime import UTC, datetime

from src.provider_adapters.sec_adapter import SECFundamentalsAdapter


def test_sec_adapter_builds_snapshot_from_normalized_record() -> None:
    snapshot = SECFundamentalsAdapter.build_snapshot_from_normalized_record(
        {
            "symbol": "MSFT",
            "as_of": "2026-03-01T00:00:00+00:00",
            "market_cap": 1000000000,
            "exchange_id": "NYS",
            "price": 300.0,
            "volume": 1000000,
            "roe": 0.22,
            "gross_margin": 0.44,
            "debt_to_equity": 0.5,
            "revenue_growth": 0.11,
            "net_income_growth": 0.12,
            "pe_ratio": 28.0,
            "peg_ratio": 1.8,
        }
    )
    assert snapshot.symbol == "MSFT"
    assert snapshot.gross_margin == 0.44


def test_sec_adapter_loads_cached_snapshots(tmp_path) -> None:
    cache_path = tmp_path / "sec_fundamentals.jsonl"
    cache_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "symbol": "AAA",
                        "as_of": "2026-02-01T00:00:00+00:00",
                        "market_cap": 1_500_000_000,
                        "exchange_id": "NYS",
                        "price": 25.0,
                        "volume": 100000.0,
                    }
                ),
                json.dumps(
                    {
                        "symbol": "BBB",
                        "as_of": "2026-04-01T00:00:00+00:00",
                        "market_cap": 1_600_000_000,
                        "exchange_id": "NYS",
                        "price": 30.0,
                        "volume": 110000.0,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    adapter = SECFundamentalsAdapter(fundamentals_cache_path=cache_path)
    snapshots = adapter.fetch_fundamentals(as_of=datetime(2026, 3, 1, tzinfo=UTC))
    assert [snapshot.symbol for snapshot in snapshots] == ["AAA"]
