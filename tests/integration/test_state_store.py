"""Integration tests for SQLite state handling."""

from datetime import UTC, datetime
from pathlib import Path

from src.models import (
    AdvisoryEnvelope,
    ClusterSnapshot,
    EventUrgency,
    LLMAdvisoryOutput,
    MLTradeFilterDecision,
    PairCandidate,
    PairPositionState,
    PairTradeIntent,
    RiskDecision,
    SentimentLabel,
    SentimentSnapshot,
    SpreadFeatures,
    SuggestedAction,
)
from src.state_store import StateStore


def test_state_store_initializes_and_persists_llm_records(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()

    store.put_llm_cache(
        cache_key="abc",
        provider="gemini",
        model_name="test-model",
        prompt_version="advisory_v1",
        response_hash="hash",
        payload={"symbol": "AAA", "sentiment_score": 0.0},
        ttl_minutes=10,
    )
    assert store.get_llm_cache("abc") == {"symbol": "AAA", "sentiment_score": 0.0}

    store.save_sentiment_snapshot(
        SentimentSnapshot(
            symbol="AAA",
            sentiment_score=0.1,
            sentiment_label=SentimentLabel.NEUTRAL,
            confidence_score=0.8,
            source_coverage_score=0.7,
            key_catalysts=["product_cycle"],
            key_risks=["valuation"],
        )
    )
    store.save_advisory_envelope(
        AdvisoryEnvelope(
            advisory=LLMAdvisoryOutput(
                symbol="AAA",
                sentiment_score=0.1,
                sentiment_label=SentimentLabel.NEUTRAL,
                confidence_score=0.8,
                key_catalysts=["product_cycle"],
                key_risks=["valuation"],
                narrative_tags=["tech"],
                event_urgency=EventUrgency.MEDIUM,
                suggested_action=SuggestedAction.CAUTION,
                rationale_short="Mixed news flow.",
                source_coverage_score=0.7,
                model_name="test-model",
                prompt_version="advisory_v1",
            ),
            decision=RiskDecision(
                symbol="AAA",
                base_weight=0.05,
                adjusted_weight=0.05,
                reason="No effect applied",
            ),
        ),
        policy_mode="observe_only",
    )
    assert len(store.latest_advisories(limit=5)) == 1


def test_state_store_persists_stat_arb_artifacts(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()
    as_of = datetime.now(UTC)
    cluster = ClusterSnapshot(
        cluster_id="cluster_001",
        as_of=as_of,
        symbols=["AAPL", "MSFT"],
        average_correlation=0.82,
        edge_count=1,
    )
    store.save_cluster_snapshots([cluster])

    candidate = PairCandidate(
        pair_id="cluster_001:AAPL:MSFT",
        cluster_id="cluster_001",
        first_symbol="AAPL",
        second_symbol="MSFT",
        spread_features=SpreadFeatures(
            pair_id="cluster_001:AAPL:MSFT",
            cluster_id="cluster_001",
            first_symbol="AAPL",
            second_symbol="MSFT",
            hedge_ratio=1.0,
            correlation=0.82,
            correlation_stability=0.74,
            current_spread=0.31,
            spread_mean=0.10,
            spread_std=0.08,
            z_score=2.2,
            mean_reversion_speed=0.16,
            half_life_days=6.0,
            transaction_cost_bps=5.0,
            expected_edge_bps=38.0,
            last_updated=as_of,
        ),
    )
    decision = MLTradeFilterDecision(
        pair_id=candidate.pair_id,
        cluster_id=candidate.cluster_id,
        execute=True,
        predicted_win_probability=0.63,
        confidence_score=0.71,
        expected_edge_bps=38.0,
        vote_ratio=0.8,
        model_version="ensemble_v1",
        rationale="fixture",
    )
    intent = PairTradeIntent(
        pair_id=candidate.pair_id,
        cluster_id=candidate.cluster_id,
        long_symbol="AAPL",
        short_symbol="MSFT",
        long_weight=0.04,
        short_weight=-0.04,
        gross_exposure=0.08,
        net_exposure=0.0,
        kelly_fraction=0.08,
        entry_z_score=2.2,
        expected_edge_bps=38.0,
        decision=decision,
    )
    store.save_pair_opportunity(as_of=as_of, candidate=candidate, status="accepted", decision=decision, intent=intent)
    store.upsert_pair_position_state(
        PairPositionState(
            pair_id=candidate.pair_id,
            cluster_id=candidate.cluster_id,
            long_symbol="AAPL",
            short_symbol="MSFT",
            opened_at=as_of,
            entry_z_score=2.2,
            latest_z_score=2.2,
            hedge_ratio=1.0,
            gross_exposure=0.08,
            net_exposure=0.0,
            kelly_fraction=0.08,
            stop_loss_z_score=3.25,
            take_profit_z_score=0.35,
            max_holding_days=15,
        )
    )

    assert store.latest_cluster_snapshots(limit=1)[0]["cluster_id"] == "cluster_001"
    assert store.latest_pair_opportunities(limit=1)[0]["pair_id"] == candidate.pair_id
    assert store.open_pair_positions()[0]["pair_id"] == candidate.pair_id
