"""Timing overlay calculations for daily bar data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

import numpy as np

from src.models import StrategyParameters, TimingFeatures


def calculate_relative_volume(volumes: Sequence[float], window: int) -> float:
    """Latest volume divided by the trailing average of prior volumes."""

    if len(volumes) < window:
        return 0.0
    lookback = np.asarray(volumes[-window:], dtype=float)
    prior = lookback[:-1]
    average = float(np.mean(prior)) if prior.size else 0.0
    if average <= 0:
        return 0.0
    return float(lookback[-1] / average)


def calculate_sma(prices: Sequence[float], window: int) -> float:
    """Simple moving average over the requested window."""

    if len(prices) < window:
        return 0.0
    return float(np.mean(np.asarray(prices[-window:], dtype=float)))


def calculate_volatility_ratio(prices: Sequence[float], window: int) -> float:
    """Recent volatility divided by prior volatility for a fixed rolling window."""

    if len(prices) < window:
        return 1.0
    series = np.asarray(prices[-window:], dtype=float)
    returns = np.diff(series) / series[:-1]
    if returns.size < 4:
        return 1.0
    midpoint = returns.size // 2
    prior = returns[:midpoint]
    recent = returns[midpoint:]
    prior_vol = float(np.std(prior))
    recent_vol = float(np.std(recent))
    if prior_vol <= 0:
        return 1.0
    return recent_vol / prior_vol


def build_timing_features(
    symbol: str,
    closes: Sequence[float],
    volumes: Sequence[float],
    strategy: StrategyParameters,
    last_updated: datetime | None = None,
) -> TimingFeatures:
    """Compute the full timing state used for the combined score."""

    timing = strategy.timing
    weights = strategy.weights
    relative_volume = calculate_relative_volume(volumes, timing.volume_window)
    volatility_ratio = calculate_volatility_ratio(closes, timing.price_window)
    short_sma = calculate_sma(closes, timing.short_sma)
    long_sma = calculate_sma(closes, timing.long_sma)

    trend_up = short_sma > long_sma > 0
    volatility_contraction = volatility_ratio <= timing.volatility_contraction_threshold

    score = 0.0
    if relative_volume > timing.relative_volume_threshold:
        score += weights.timing_relative_volume
    if volatility_contraction:
        score += weights.timing_volatility_contraction
    if trend_up:
        score += weights.timing_trend

    return TimingFeatures(
        symbol=symbol,
        relative_volume=round(relative_volume, 6),
        volatility_ratio=round(volatility_ratio, 6),
        short_sma=round(short_sma, 6),
        long_sma=round(long_sma, 6),
        trend_up=trend_up,
        volatility_contraction=volatility_contraction,
        timing_score=round(score, 6),
        last_updated=last_updated or datetime.now(UTC),
    )
