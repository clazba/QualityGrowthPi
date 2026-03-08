# QualityGrowthPi

Self-hosted LEAN-compatible quant trading stack for Raspberry Pi 5, designed to preserve a QuantConnect-style quality-growth US equities strategy while adding local operational hardening, persistence, regression testing, and an optional auditable LLM advisory subsystem.

## Key Properties

- bare-metal-first Python tooling
- LEAN workspace compatibility under `lean_workspace/`
- deterministic strategy logic extracted into testable Python modules
- SQLite WAL state store for restart safety and auditability
- optional LLM advisory path with strict policy gating and fail-open behaviour
- NVMe-oriented runtime layout for logs, results, state, and caches

## Layout

- `src/`: shared Python modules, persistence, risk policy, providers, and LLM advisory components
- `lean_workspace/`: LEAN project layout and algorithm entrypoint
- `scripts/`: Pi bootstrap, environment setup, verification, test, and execution scripts
- `config/`: YAML configuration and local prompt templates
- `tests/`: unit, integration, regression, and LLM contract tests
- `docs/`: architecture, operations, deployment, provider fidelity, security, and LLM design notes

## Target Runtime

The intended Pi deployment path is `/mnt/nvme_data/shared/quant_gpt`. This scaffold is generated in the current workspace path and uses repository-relative defaults so it can be validated locally first. On the Pi, set `QUANT_GPT_RUNTIME_ROOT=/mnt/nvme_data/shared/quant_gpt` in `.env`.

## Fast Start

```bash
make setup
make env
make verify
make test
make smoke
make llm-smoke
make e2e
```

For an operator-focused setup and usage guide, see [docs/quickstart.md](/Volumes/PiShare/quant_gpt/docs/quickstart.md).

## Execution Paths

- Backtest: `make backtest` (`QuantConnect cloud` is the default and validated path)
- Stat-arb price-history export: `python scripts/export_stat_arb_price_history.py --lean-data-root <dir> --output <file>` (reads LEAN-style daily equity data and writes the aligned JSON consumed by the trainer)
- Stat-arb model upload: `make upload-stat-arb-model` (validates a versioned sklearn/joblib artifact locally, then uploads it to QuantConnect Object Store)
- Stat-arb model training: `python scripts/train_stat_arb_softvote.py --price-history-json <file> --artifact-output <file>` (builds supervised pair samples, runs walk-forward grid search across the five-model soft-voting ensemble, and writes the joblib artifact contract expected by the cloud loader)
- Operator workflow: `make workflow` (builds the deterministic opportunity report, loads recent news, runs LLM advisory review for current paper candidates, and writes a markdown report under `results/opportunities/`)
- Paper trading: `make paper-check`, `./scripts/list_qc_nodes.sh`, `make live-paper`, `make paper-status`, `make paper-stop` (`Alpaca paper` via `QuantConnect cloud + Alpaca brokerage` is the default first stage)
- LLM advisory history: `make llm-report`
- Live provider path: `scripts/run_live_provider.sh`
- Baseline capture: `make baseline BACKTEST_ID=<cloud_backtest_id>`

## Validated Operator Flow

The repository has been validated on the Pi for:

- cloud backtests with QuantConnect project sync via API
- cloud paper deployment with Alpaca brokerage
- online end-to-end validation via `./scripts/run_e2e.sh --online`
- regression and unit coverage across the shared control plane and LEAN workspace

Typical operator sequence:

```bash
make verify
make test
make backtest
make paper-check
./scripts/list_qc_nodes.sh
make live-paper
make paper-status
```

## Stat-Arb Model Inference

The graph stat-arb strategy now supports two ML filter backends:

- `embedded_scorecard`
  - deterministic built-in fallback
- `object_store_model`
  - loads a pinned sklearn/joblib artifact from QuantConnect Object Store inside the cloud algorithm process

Pinned environment variables for `object_store_model` mode:

- `STAT_ARB_ML_FILTER_MODE=object_store_model`
- `STAT_ARB_ML_MODEL_VERSION=softvote_v2026_03_08`
- `STAT_ARB_OBJECT_STORE_MODEL_KEY=28761844/stat-arb/models/softvote_v2026_03_08/ensemble.joblib`
- `STAT_ARB_FEATURE_SCHEMA_VERSION=stat_arb_v1`
- `STAT_ARB_ML_FALLBACK_MODE=embedded_scorecard`

Recommended Object Store key shape:

```text
<project_id>/stat-arb/models/<model_version>/ensemble.joblib
```

Upload flow:

```bash
make upload-stat-arb-model
```

The upload command validates the artifact contract before it calls:

- `lean cloud object-store set <key> <artifact_path>`

Artifact contract requirements:

- `schema_version`
- `model_version`
- `feature_names`
- `pipeline` with `predict_proba`
- optional `global_feature_importance`
- optional `training_metadata`

Pinned feature order:

- `abs_z_score`
- `correlation`
- `correlation_stability`
- `mean_reversion_speed`
- `half_life_score`
- `expected_edge_bps_norm`
- `transaction_cost_penalty`

## Current Limits

- cloud backtests can bypass local dataset downloads while keeping the repository on-prem; fully local backtests still require licensed local-compatible datasets
- cloud Alpaca paper deployment requires an available QuantConnect live node; `Quant Researcher` allows live-node usage but does not automatically provision one for free
- the first local fallback stack is Massive + SEC + Alpaca + Alpha Vantage, which is designed for staged paper/live approximation rather than exact QuantConnect parity
- provider adapters for Massive, Alpaca, Alpha Vantage, SEC, IBKR, and Gemini are scaffolded with safety guards and offline fallbacks, not fully credentialed here
- LEAN engine execution depends on the local host having `lean` installed and authenticated

See [docs/architecture.md](/Volumes/PiShare/quant_gpt/docs/architecture.md), [docs/deployment.md](/Volumes/PiShare/quant_gpt/docs/deployment.md), and [docs/data-providers.md](/Volumes/PiShare/quant_gpt/docs/data-providers.md).
