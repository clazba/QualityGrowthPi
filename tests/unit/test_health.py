"""Unit tests for runtime health helpers."""

from datetime import UTC, datetime, timedelta

from src.health import stale_data_detected


def test_stale_data_detected_allows_recent_daily_bar_gap() -> None:
    now = datetime(2026, 3, 9, 9, 30, tzinfo=UTC)
    last_updated = datetime(2026, 3, 6, 16, 0, tzinfo=UTC)
    assert stale_data_detected(last_updated, max_age_minutes=30, now=now) is False


def test_stale_data_detected_rejects_older_gap() -> None:
    now = datetime(2026, 3, 9, 9, 30, tzinfo=UTC)
    last_updated = now - timedelta(days=5)
    assert stale_data_detected(last_updated, max_age_minutes=30, now=now) is True


def test_stale_data_detected_allows_long_weekend_gap() -> None:
    now = datetime(2026, 5, 26, 9, 30, tzinfo=UTC)
    last_updated = datetime(2026, 5, 22, 16, 0, tzinfo=UTC)
    assert stale_data_detected(last_updated, max_age_minutes=30, now=now) is False
