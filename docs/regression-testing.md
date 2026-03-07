# Regression Testing Strategy

## Purpose

The first production cut prioritizes behavioural preservation over speculative optimization. Regression scaffolding exists to compare local runs against later-captured QuantConnect baselines.

## Comparison Artefacts

Store or generate fixtures for:

- universe snapshots
- fundamental ranking tables
- timing score tables
- rebalance intents
- target weights
- order event streams
- holdings snapshots
- sentiment snapshots
- advisory outputs
- policy influence decisions

## Test Categories

### Unit

- pure scoring thresholds and ranking
- timing overlays
- settings parsing
- risk policy caps

### Integration

- SQLite schema setup and WAL settings
- rebalance guard idempotency
- restart recovery reads
- provider and advisory cache metadata

### LLM Contract

- schema validation
- prompt loading
- fail-open behaviour when the provider is down
- policy influence caps

### Regression

Fixtures are intentionally small and deterministic. Once QuantConnect baseline artefacts are available, extend the regression folder with symbol-by-symbol comparison bundles.

## Acceptance Rule

Do not “improve” scoring or execution logic until a baseline comparison exists and the impact is measurable.
