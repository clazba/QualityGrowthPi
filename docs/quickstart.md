# User Guide

This guide explains how to use `quant_gpt` day to day on the Pi.

Run all commands from the repo root unless stated otherwise:

```bash
cd /mnt/nvme_data/shared/quant_gpt
```

## What You Built

`quant_gpt` combines:

- a deterministic quality-growth stock-selection strategy
- QuantConnect cloud backtesting
- QuantConnect cloud paper trading with Alpaca brokerage
- local operator reporting and regression tooling
- an optional LLM advisory layer used for narrative review

Validated default operating model:

- backtests: QuantConnect cloud
- paper trading: QuantConnect cloud + Alpaca paper
- operator reports: local on the Pi
- LLM mode: `observe_only`
- stat-arb ML inference: QuantConnect cloud Object Store model artifact with embedded scorecard fallback

## The Commands You Will Use Most

```bash
make verify
make test
make backtest
make workflow
make llm-report
make upload-stat-arb-model
python scripts/train_stat_arb_softvote.py --price-history-json <file> --artifact-output <file>
make paper-check
make live-paper
make paper-status
make paper-stop
make e2e
```

What they mean:

- `make verify`
  - checks Python, imports, script syntax, and test discovery
- `make test`
  - runs the full regression suite
- `make backtest`
  - runs the validated cloud backtest path
- `make workflow`
  - builds the operator opportunity report and LLM advisory review
- `make llm-report`
  - prints saved LLM advisories from SQLite
- `make upload-stat-arb-model`
  - validates and uploads the pinned stat-arb sklearn/joblib artifact to QuantConnect Object Store
- `python scripts/train_stat_arb_softvote.py --price-history-json <file> --artifact-output <file>`
  - generates supervised stat-arb pair samples from aligned close history, fits the five-model soft-voting ensemble, and writes the joblib artifact
- `make paper-check`
  - validates Alpaca paper credentials and account reachability
- `make live-paper`
  - starts the cloud paper deployment
- `make paper-status`
  - shows whether the paper deployment is running
- `make paper-stop`
  - stops the paper deployment
- `make e2e`
  - runs the end-to-end validation harness

## First-Time Setup

### 1. Bootstrap The Environment

```bash
make setup
```

Expected result:

- `.venv` is created
- Python dependencies are installed
- LEAN CLI is installed or validated

### 2. Create `.env`

```bash
make env
```

Recommended starting values:

- `BACKTEST_MODE=cloud`
- `PAPER_DEPLOYMENT_TARGET=cloud`
- `PAPER_BROKER=alpaca`
- `PAPER_ENVIRONMENT=paper`
- `LEAN_BACKTEST_PROJECT=QualityGrowthPi`
- `LEAN_BACKTEST_PROJECT_ID=<your_project_id>`
- `QC_CLOUD_FILE_SYNC=true`
- `LEAN_CLOUD_OPEN_RESULTS=false`
- `LEAN_CLOUD_OPEN_PAPER=false`
- `LLM policy mode=observe_only`

Safety defaults to keep:

- `LLM policy mode=observe_only`
- `PAPER_ENVIRONMENT=paper`
- cloud backtests enabled
- no local backtest mode unless you intentionally have the required licensed data

### 3. Validate Before Trusting Anything

```bash
make verify
make test
make e2e
```

If these are not green, fix them before trusting backtests or paper trading.

### 4. Optional: Enable Cloud-Embedded Stat-Arb Model Inference

Use this only when you are ready to switch the graph stat-arb strategy from the embedded scorecard to a pinned Object Store model artifact.

Recommended `.env` values:

- `STAT_ARB_ML_FILTER_MODE=object_store_model`
- `STAT_ARB_ML_MODEL_VERSION=softvote_v2026_03_08`
- `STAT_ARB_OBJECT_STORE_MODEL_KEY=28761844/stat-arb/models/softvote_v2026_03_08/ensemble.joblib`
- `STAT_ARB_FEATURE_SCHEMA_VERSION=stat_arb_v1`
- `STAT_ARB_ML_FALLBACK_MODE=embedded_scorecard`

Upload the validated artifact:

```bash
make upload-stat-arb-model
```

What this does:

- validates the local joblib artifact contract
- checks the pinned schema version and model version
- uploads the exact artifact to QuantConnect Object Store
- keeps the embedded scorecard as the required fallback if load or inference fails

## Common Use Cases

### Use Case 1: Morning Health Check

Use this when:

- the Pi restarted
- you updated code
- you changed config
- you want to confirm the paper deployment is still healthy

Commands:

```bash
make verify
make test
make paper-status
```

### Use Case 2: Run A Fresh Backtest

Use this when:

- you changed strategy code
- you changed provider settings
- you want a fresh validation before paper trading

Commands:

```bash
make backtest
./scripts/read_backtest_diagnostics.sh <backtest_id>
```

What to inspect:

- return
- drawdown
- total orders
- closed trades
- `LastSuccessfulTargetCount`
- `LastRebalanceCheckState`

### Use Case 3: Review Current Market Opportunities

Use this when:

- you want to know what the strategy currently likes
- you want to compare the cloud backtest output to current paper positions
- you want recent-news commentary on current paper symbols

Commands:

```bash
make workflow
make llm-report
```

Outputs:

- markdown report:
  - `results/opportunities/trade_workflow_<timestamp>.md`
- LLM summary JSON:
  - `results/opportunities/llm_workflow_latest.json`

What the workflow report includes:

- fundamental universe settings
- ranking rules
- timing filters
- current backtest validation summary
- current Alpaca paper positions
- LLM advisory review of the current paper candidates

### Use Case 4: Start Alpaca Paper Trading

Use this when:

- backtests are healthy
- Alpaca paper credentials are configured
- a QuantConnect live node is available

Commands:

```bash
make paper-check
./scripts/list_qc_nodes.sh
make live-paper
make paper-status
```

Important note:

- the first cloud paper deployment may print a QuantConnect authorization URL that you need to open in a browser to authorize the Alpaca connection

### Use Case 5: Stop Paper Trading

Use this when:

- the workflow report deteriorates
- you see unexpected position drift
- the broker or deployment looks unhealthy

Commands:

```bash
make paper-stop
```

Emergency liquidation:

```bash
make paper-liquidate
```

### Use Case 6: Capture A Regression Baseline

Use this after a successful cloud backtest that you want to preserve as a reference point.

Commands:

```bash
./scripts/read_backtest_diagnostics.sh <backtest_id>
make baseline BACKTEST_ID=<backtest_id>
```

Outputs:

- `results/backtests/cloud/<backtest_id>.json`
- `lean_workspace/QualityGrowthPi/tests/regression/cloud_baselines/<backtest_id>/`
- updated `lean_workspace/QualityGrowthPi/tests/regression/baseline_manifest.json`

### Use Case 7: Upload A New Stat-Arb ML Model

Use this when:

- you trained a new sklearn/joblib ensemble offline
- the artifact bundles its preprocessing
- you want QuantConnect cloud backtests and live runs to use the same pinned model

Commands:

```bash
make upload-stat-arb-model
```

If you want to override the defaults directly:

```bash
./scripts/upload_stat_arb_model.sh /path/to/ensemble.joblib stat-arb/models/<model_version>/ensemble.joblib
```

Artifact contract:

- `schema_version`
- `model_version`
- `feature_names`
- `pipeline` with `predict_proba`
- optional `global_feature_importance`
- optional `training_metadata`

Pinned stat-arb inference feature order:

- `abs_z_score`
- `correlation`
- `correlation_stability`
- `mean_reversion_speed`
- `half_life_score`
- `expected_edge_bps_norm`
- `transaction_cost_penalty`

## Examples

### Example: Normal Morning Operator Flow

```bash
cd /mnt/nvme_data/shared/quant_gpt
make verify
make paper-status
make workflow
make llm-report
```

### Example: Validate A Code Change Before Trusting Paper

```bash
cd /mnt/nvme_data/shared/quant_gpt
make test
make e2e
make backtest
./scripts/read_backtest_diagnostics.sh <backtest_id>
make baseline BACKTEST_ID=<backtest_id>
```

### Example: Restart Paper After A Config Change

```bash
cd /mnt/nvme_data/shared/quant_gpt
make paper-stop
make paper-check
make live-paper
make paper-status
```

### Example: Get A Manual Opportunity Review Before Market Open

```bash
cd /mnt/nvme_data/shared/quant_gpt
make workflow
make llm-report
sed -n '1,220p' results/opportunities/trade_workflow_*.md
```

### Example: Run The Workflow And Force A Fresh Backtest First

```bash
cd /mnt/nvme_data/shared/quant_gpt
./scripts/run_trade_workflow.sh --run-backtest
```

### Example: Reuse A Known Backtest And Capture It As A Baseline

```bash
cd /mnt/nvme_data/shared/quant_gpt
./scripts/run_trade_workflow.sh --backtest-id <backtest_id> --capture-baseline
```

## How To Read The Workflow Report

The workflow report is the main operator summary.

If it says the opportunity set is healthy, that means:

- the deterministic universe, ranking, and timing path produced a real target basket
- the latest cloud backtest diagnostics are valid
- the current paper deployment can be interpreted normally

It does not mean:

- the LLM is selecting stocks
- the LLM is placing orders

The LLM remains a secondary narrative and risk layer.

### How To Use The LLM Section

The LLM section tells you:

- whether recent news was available
- whether Gemini returned usable advisories
- whether any holdings were flagged as `caution`, `manual_review`, or `reduce_size`

In the default `observe_only` mode:

- advisories are stored and shown
- they do not change orders

### How To Use The Paper Positions Section

Treat the current Alpaca paper positions as the operational view of what the deployed strategy currently wants to hold.

If the workflow report and current paper positions look inconsistent, investigate before trusting the deployment.

## Helpful Files

Important outputs:

- cloud backtest diagnostics:
  - `results/backtests/cloud/<backtest_id>.json`
- workflow reports:
  - `results/opportunities/trade_workflow_<timestamp>.md`
- LLM workflow summary:
  - `results/opportunities/llm_workflow_latest.json`
- e2e outputs:
  - `results/e2e/`

Useful scripts:

- `scripts/read_backtest_diagnostics.sh`
- `scripts/run_trade_workflow.sh`
- `scripts/check_alpaca_paper.sh`
- `scripts/paper_status.sh`
- `scripts/list_qc_nodes.sh`
- `scripts/llm_report.sh`

## Control Plane Commands

The local control-plane entrypoint is `src/main.py`.

Useful commands:

```bash
. .venv/bin/activate
python -m src.main health
python -m src.main init-db
python -m src.main provider-plan
./scripts/llm_report.sh
```

What they do:

- `health`
  - initializes logging, runtime lock, and heartbeat
- `init-db`
  - initializes the SQLite state store
- `provider-plan`
  - prints the resolved backtest, paper, and local provider plan
- `llm-report`
  - prints the latest stored advisory records

## Common Problems

### `make verify` fails because `pytest` or another dependency is missing

Re-run:

```bash
make setup
```

Or manually:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r requirements.txt
```

### LEAN CLI is installed but cloud commands fail

Check:

```bash
lean whoami
grep '^LEAN_ORGANIZATION_ID=' .env
grep -n '"job-organization-id"' lean_workspace/lean.json
```

The organization id must be the real QuantConnect organization id, not a display name.

### `make llm-report` shows `[]`

This means no advisory records are stored yet.

Run:

```bash
make workflow
cat results/opportunities/llm_workflow_latest.json
```

Common causes:

- no recent news
- Gemini credentials missing
- no current paper positions
- model output failed schema validation

### Cloud logs are not available

This is a known practical limit in the current workflow.

Use:

- `./scripts/read_backtest_diagnostics.sh <backtest_id>`
- the saved diagnostics JSON
- the workflow report

instead of relying on `lean logs`.

### QuantConnect node errors in paper deploy

Run:

```bash
./scripts/list_qc_nodes.sh
```

Then set:

- `LEAN_CLOUD_PAPER_NODE=<node_id_or_name>`

### Git lock errors

If you hit `.git/index.lock`, confirm no Git process is running and then remove the stale lock file before retrying.

## Where To Go Next

Use these docs when you want more depth:

- [docs/deployment.md](/Volumes/PiShare/quant_gpt/docs/deployment.md)
- [docs/operations.md](/Volumes/PiShare/quant_gpt/docs/operations.md)
- [docs/data-providers.md](/Volumes/PiShare/quant_gpt/docs/data-providers.md)
- [docs/llm-agent.md](/Volumes/PiShare/quant_gpt/docs/llm-agent.md)
- [docs/regression-testing.md](/Volumes/PiShare/quant_gpt/docs/regression-testing.md)
