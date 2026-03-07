# Regression Testing

## Goal

Regression testing in this repo is about preserving validated strategy behavior while you improve tooling, workflow, or integrations.

Main rule:

- do not change deterministic strategy behavior casually once a good cloud baseline exists

## What Counts As A Baseline

A baseline is a completed QuantConnect cloud backtest whose diagnostics are saved locally and then captured into the regression bundle.

Normal sequence:

```bash
make backtest
./scripts/read_backtest_diagnostics.sh <backtest_id>
make baseline BACKTEST_ID=<backtest_id>
```

This writes:

- `results/backtests/cloud/<backtest_id>.json`
- `lean_workspace/QualityGrowthPi/tests/regression/cloud_baselines/<backtest_id>/`

And updates:

- `lean_workspace/QualityGrowthPi/tests/regression/baseline_manifest.json`

## Test Layers

### Unit Tests

Focus on:

- scoring thresholds
- ranking logic
- timing logic
- settings parsing
- provider adapters
- workflow helper logic
- LLM payload parsing and repair behavior

Run:

```bash
make test
```

### Integration Tests

Focus on:

- SQLite schema and WAL behavior
- rebalance idempotency
- advisory persistence
- LEAN workspace config validity

### LLM Contract Tests

Focus on:

- prompt loading
- schema validation
- fail-open behavior
- policy bounds
- repair of common Gemini alias-style responses

Run:

```bash
make llm-smoke
```

### End-To-End Validation

Focus on:

- installation health
- provider-plan resolution
- state-store validation
- workflow and script integrity
- optional online provider probes

Run:

```bash
make e2e
./scripts/run_e2e.sh --online
```

## What To Compare When Strategy Logic Changes

Compare these against the current baseline:

- fine universe counts
- ranked candidate counts
- target counts
- rebalance state
- order counts
- turnover
- net profit and drawdown
- current paper holdings drift if paper is already running

For LLM-related changes, compare:

- whether advisories are saved at all
- advisory counts by symbol
- caution and manual-review frequency
- whether `observe_only` remains non-invasive

## Acceptance Rule

Accept a change only when one of these is true:

- behavior is materially unchanged versus the baseline
- the behavior change is intentional and documented
- the improvement is measurable and the operator accepts the trade-off

## Practical Guidance

- tooling-only changes can usually be accepted with green tests and e2e checks
- deterministic strategy changes should be paired with a fresh cloud backtest review
- provider changes should be checked with both tests and workflow output
- LLM changes should preserve fail-open behavior and should not create hidden trade influence in `observe_only`
