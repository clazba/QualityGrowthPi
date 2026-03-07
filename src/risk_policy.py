"""Deterministic policy gates for optional LLM advisory influence."""

from __future__ import annotations

from src.models import LLMAdvisoryOutput, LLMMode, LLMPolicyConfig, RiskDecision, SuggestedAction


def apply_advisory_policy(
    base_weight: float,
    advisory: LLMAdvisoryOutput | None,
    mode: LLMMode,
    policy: LLMPolicyConfig,
) -> RiskDecision:
    """Apply bounded, deterministic policy rules to an advisory payload."""

    if advisory is None:
        return RiskDecision(
            symbol="unknown",
            base_weight=base_weight,
            adjusted_weight=base_weight,
            reason="No advisory payload available",
        )

    decision = RiskDecision(
        symbol=advisory.symbol,
        base_weight=base_weight,
        adjusted_weight=base_weight,
        action_taken=advisory.suggested_action,
        reason="Advisory observed but not applied",
    )

    if mode in {LLMMode.DISABLED, LLMMode.OBSERVE_ONLY, LLMMode.ADVISORY_ONLY}:
        return decision

    if advisory.confidence_score < policy.low_confidence_threshold:
        decision.action_taken = SuggestedAction.NO_EFFECT
        decision.reason = "Advisory confidence below deterministic threshold"
        return decision

    if advisory.source_coverage_score < policy.low_coverage_threshold:
        decision.action_taken = SuggestedAction.NO_EFFECT
        decision.reason = "Advisory source coverage below deterministic threshold"
        return decision

    if advisory.suggested_action == SuggestedAction.REDUCE_SIZE:
        reduction = policy.max_weight_reduction * advisory.confidence_score
        decision.adjusted_weight = round(base_weight * max(0.0, 1.0 - reduction), 6)
        decision.applied = True
        decision.reason = "Applied bounded reduce_size policy"
        if policy.require_manual_review_on_reduce_size:
            decision.manual_review_required = True
        return decision

    if advisory.suggested_action == SuggestedAction.MANUAL_REVIEW:
        decision.manual_review_required = True
        decision.reason = "Manual review required by advisory policy"
        return decision

    if advisory.suggested_action == SuggestedAction.CAUTION:
        decision.reason = "Caution flagged; deterministic weight unchanged"
        return decision

    decision.action_taken = SuggestedAction.NO_EFFECT
    decision.reason = "No deterministic effect applied"
    return decision
