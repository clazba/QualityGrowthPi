"""Unit tests for Massive financials and news normalization."""

from datetime import UTC, datetime

from src.provider_adapters.news_base import MassiveNewsProvider
from src.provider_adapters.polygon_adapter import MassiveAdapter


def test_normalize_ratio_record_supports_documented_field_names() -> None:
    adapter = MassiveAdapter(api_key="test-key")
    record = {
        "ticker": "AAPL",
        "date": "2025-10-20",
        "price": 262.24,
        "average_volume": 54815761.0,
        "market_cap": 3891743873600.0,
        "earnings_per_share": 6.69,
        "price_to_earnings": 39.2,
        "return_on_equity": 1.5081,
        "debt_to_equity": 1.54,
    }
    normalized = adapter._normalize_ratio_record(record)
    assert normalized is not None
    assert normalized["ticker"] == "AAPL"
    assert normalized["price_to_earnings"] == 39.2
    assert normalized["return_on_equity"] == 1.5081


def test_normalize_income_statement_record_supports_documented_fields() -> None:
    adapter = MassiveAdapter(api_key="test-key")
    record = {
        "tickers": ["AAPL"],
        "period_end": "2024-09-28",
        "filing_date": "2025-08-01",
        "fiscal_quarter": 4,
        "fiscal_year": 2024,
        "timeframe": "quarterly",
        "revenue": 94930000000.0,
        "gross_profit": 43879000000.0,
        "consolidated_net_income_loss": 14736000000.0,
    }
    normalized = adapter._normalize_income_statement_record(record)
    assert normalized is not None
    assert normalized["ticker"] == "AAPL"
    assert normalized["gross_profit"] == 43879000000.0
    assert normalized["net_income"] == 14736000000.0


def test_massive_news_provider_normalizes_reference_news_articles() -> None:
    provider = MassiveNewsProvider(api_key="test-key")
    record = {
        "id": "article-1",
        "publisher": {"name": "The Motley Fool"},
        "title": "Why Shares of Dell Technologies Rose 11.5% in April",
        "published_utc": datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
        "article_url": "https://example.com/article",
        "description": "Dell confirmed a previous strategy to spin off its stake in VMware.",
        "tickers": ["DELL", "VMW"],
    }
    events = provider._normalize_news_record(record, requested=["DELL", "VMW"])
    assert len(events) == 2
    assert events[0].source == "The Motley Fool"
    assert events[0].headline.startswith("Why Shares of Dell")
    assert events[1].symbol == "VMW"


def test_massive_news_provider_uses_multi_ticker_query_extension() -> None:
    provider = MassiveNewsProvider(api_key="test-key")
    calls: list[tuple[str, dict | None]] = []

    def fake_paginate(path_or_url: str, params: dict | None = None) -> list[dict]:
        calls.append((path_or_url, params))
        return []

    provider._paginate_results = fake_paginate  # type: ignore[method-assign]
    provider.fetch_news(["AAPL", "MSFT"])
    assert calls[0][0] == provider.news_path_template
    assert calls[0][1] is not None
    assert calls[0][1]["ticker.any_of"] == "AAPL,MSFT"
