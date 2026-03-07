# Deployment

## Supported Deployment Paths

The repo currently supports three practical paths.

### 1. Local Validation

Use this for:

- first-time setup
- dependency checks
- smoke tests
- regression tests
- operator workflow generation

Main commands:

- `make setup`
- `make env`
- `make verify`
- `make test`
- `make smoke`
- `make llm-smoke`
- `make e2e`

### 2. Cloud Backtest

Use this for:

- validated strategy backtests
- baseline capture
- parity-first research

Main command:

- `make backtest`

What happens:

1. local config is synced into `lean_workspace/`
2. the cloud LEAN project is synced by API
3. `lean cloud backtest` is launched
4. diagnostics are saved locally under `results/backtests/cloud/`

Important requirements:

- `lean` installed
- QuantConnect CLI login available
- `LEAN_BACKTEST_PROJECT_ID` configured
- QuantConnect organization with cloud backtest access

### 3. Cloud Paper Trading With Alpaca

Use this for:

- the first brokered validation stage
- ongoing operational monitoring of current strategy holdings

Main commands:

- `make paper-check`
- `./scripts/list_qc_nodes.sh`
- `make live-paper`
- `make paper-status`
- `make paper-stop`

What happens:

1. Alpaca paper credentials are validated locally
2. LEAN workspace and project config are synced
3. QuantConnect cloud live deploy is launched
4. Alpaca is used as the brokerage
5. QuantConnect hosts the running strategy

Important requirements:

- `lean` installed
- QuantConnect CLI login available
- `LEAN_BACKTEST_PROJECT_ID` configured
- `LEAN_CLOUD_PAPER_NODE` configured
- an available QuantConnect live node
- Alpaca paper API credentials

Important practical note:

- the first deploy may print a QuantConnect authorization URL that you need to open in a browser to authorize the Alpaca connection

## Paths That Are Not The Default

### Local Backtest

This remains supported in principle, but it is not the recommended path.

Use it only if you intentionally choose:

- local LEAN execution
- local compatible datasets
- the extra operational and licensing burden that comes with parity-grade local data

### Local Paper Or Local Live

This is a later-stage path.

It is not the first recommended deployment mode because:

- the strategy depends on a dynamic fundamental universe
- the validated path today is QuantConnect cloud execution
- the local fallback provider stack is designed for approximation and operator support, not exact parity

## Recommended Environment Settings

The most important settings are:

- `BACKTEST_MODE=cloud`
- `PAPER_DEPLOYMENT_TARGET=cloud`
- `PAPER_BROKER=alpaca`
- `PAPER_ENVIRONMENT=paper`
- `LEAN_BACKTEST_PROJECT=QualityGrowthPi`
- `LEAN_BACKTEST_PROJECT_ID=<project_id>`
- `LEAN_CLOUD_PAPER_NODE=<node_id_or_name>`
- `QC_CLOUD_FILE_SYNC=true`
- `LEAN_CLOUD_OPEN_RESULTS=false`
- `LEAN_CLOUD_OPEN_PAPER=false`

## Runtime Layout

Persistent runtime content normally lives under:

- `/mnt/nvme_data/shared/quant_gpt/logs`
- `/mnt/nvme_data/shared/quant_gpt/state`
- `/mnt/nvme_data/shared/quant_gpt/data`
- `/mnt/nvme_data/shared/quant_gpt/results`

Important outputs:

- cloud backtest diagnostics: `results/backtests/cloud/`
- workflow reports: `results/opportunities/`
- e2e artefacts: `results/e2e/`

## Recommended Validation Sequence

Use this order:

1. `make verify`
2. `make test`
3. `make e2e`
4. `make backtest`
5. `./scripts/read_backtest_diagnostics.sh <backtest_id>`
6. `make baseline BACKTEST_ID=<backtest_id>`
7. `make paper-check`
8. `./scripts/list_qc_nodes.sh`
9. `make live-paper`
10. `make paper-status`

## Operational Notes

- browser auto-open is suppressed by default on headless systems
- QuantConnect API file sync is preferred over relying only on cloud push
- cloud log retrieval through `lean logs` is not reliable enough to be the main diagnostics path
- saved diagnostics JSON, workflow reports, and paper status are the primary operator inspection tools
