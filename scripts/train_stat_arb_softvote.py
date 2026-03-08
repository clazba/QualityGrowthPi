#!/usr/bin/env python3
"""Train and export the graph stat-arb soft-voting ensemble artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np

from src.stat_arb.training import (
    build_artifact_payload,
    build_training_samples,
    fit_soft_voting_ensemble,
    load_price_history_json,
    samples_to_matrix,
    save_training_samples_jsonl,
)
from src.strategy_settings import load_stat_arb_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-history-json", required=True, help="JSON file containing aligned symbol close history")
    parser.add_argument("--artifact-output", required=True, help="Output joblib artifact path")
    parser.add_argument("--report-output", help="Optional JSON training report path")
    parser.add_argument("--samples-output", help="Optional JSONL path for generated training samples")
    parser.add_argument("--settings-profile", default="default", help="Stat-arb settings profile name")
    parser.add_argument("--model-version", default="softvote_v2026_03_08", help="Artifact model version")
    parser.add_argument("--feature-schema-version", default="stat_arb_v1", help="Pinned feature schema version")
    parser.add_argument("--cv-splits", type=int, default=5, help="Walk-forward cross-validation split count")
    parser.add_argument("--sample-step", type=int, default=1, help="Take every Nth rebalance day when generating labels")
    parser.add_argument("--max-samples", type=int, default=0, help="Keep only the most recent N samples (0 means all)")
    parser.add_argument("--random-state", type=int, default=42, help="Random seed for sklearn estimators")
    parser.add_argument("--n-jobs", type=int, default=-1, help="Parallel worker count for grid search")
    parser.add_argument("--scoring", default="neg_log_loss", help="GridSearchCV scoring metric")
    parser.add_argument(
        "--estimators",
        default="mlp,adaboost,hist_gradient_boosting,sgd,logistic_regression",
        help="Comma-separated estimator ids to include in the soft-voting ensemble",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = load_stat_arb_settings(args.settings_profile)
    price_history, calendar = load_price_history_json(args.price_history_json)
    samples = build_training_samples(
        price_history,
        settings,
        calendar=calendar,
        sample_step=args.sample_step,
        max_samples=args.max_samples,
    )
    X, y = samples_to_matrix(samples)
    estimator_names = [name.strip() for name in args.estimators.split(",") if name.strip()]
    ensemble = fit_soft_voting_ensemble(
        X,
        y,
        cv_splits=args.cv_splits,
        scoring=args.scoring,
        random_state=args.random_state,
        n_jobs=args.n_jobs,
        selected_estimators=estimator_names,
    )

    report = {
        "artifact_output": str(Path(args.artifact_output).expanduser().resolve()),
        "settings_profile": args.settings_profile,
        "model_version": args.model_version,
        "feature_schema_version": args.feature_schema_version,
        "sample_count": len(samples),
        "positive_rate": round(float(np.mean(y)), 6),
        "cv_splits": args.cv_splits,
        "sample_step": args.sample_step,
        "max_samples": args.max_samples,
        "random_state": args.random_state,
        "scoring": args.scoring,
        "estimators": estimator_names,
        "member_reports": ensemble.member_reports,
        "global_feature_importance": ensemble.global_feature_importance,
    }

    payload = build_artifact_payload(
        ensemble=ensemble,
        model_version=args.model_version,
        feature_schema_version=args.feature_schema_version,
        training_metadata=report,
    )

    artifact_output = Path(args.artifact_output).expanduser().resolve()
    artifact_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, artifact_output)

    if args.samples_output:
        save_training_samples_jsonl(samples, args.samples_output)
        report["samples_output"] = str(Path(args.samples_output).expanduser().resolve())

    if args.report_output:
        report_output = Path(args.report_output).expanduser().resolve()
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
