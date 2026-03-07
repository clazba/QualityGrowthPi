# Data Providers and Fidelity Caveats

## Goal

Preserve the original QuantConnect strategy behaviour as closely as possible while acknowledging that external self-hosted environments may not replicate every licensed data source or point-in-time transformation exactly.

## Supported Modes

### QuantConnect Local Compatible Mode

Use this mode when the operator has LEAN CLI access and appropriate local datasets.

Strengths:

- best path toward matching LEAN universe and corporate action behaviour
- direct compatibility with workspace-driven backtests

Risks:

- local data licensing and availability
- exact Morningstar field equivalence may depend on dataset packages

### QuantConnect Cloud Backtest Mode

Use this mode when the goal is to preserve QuantConnect dataset behaviour for backtests without downloading local copies of the datasets.

Strengths:

- best cost-to-fidelity option for this repository's backtesting workflow
- keeps the repository on-prem while pushing the local LEAN project for remote execution
- avoids local dataset download charges and local data maintenance

Risks:

- still depends on QuantConnect cloud availability and organization entitlements
- code is executed remotely for cloud backtests, so this is not an offline workflow
- local live or local backtest parity still requires separate validation if local execution is later enabled

### Repository Default Local Fallback Stack

The repository's first local fallback stack is:

- `fundamentals`: Massive + SEC + Alpha Vantage
- `daily bars`: Alpaca, with Massive and Alpha Vantage as fallbacks
- `news`: composite provider using local file cache, Alpha Vantage, and Massive

Strengths:

- aligns with the lowest-cost staged deployment decision for this repository
- keeps free/public SEC data in the loop for validation and cache building
- uses Alpaca for the first paper-broker path and local daily-bar fallback

Risks:

- still drifts from QuantConnect/Morningstar point-in-time behavior
- depends on local cache population for fundamentals snapshots
- Alpha Vantage and Massive remain auxiliary for local live approximation, not parity-grade substitutes

### External Equivalent Mode

Use this mode when local QuantConnect-compatible data is unavailable.

Strengths:

- allows local development and partial validation
- can support operator workflows and advisory enrichment

Risks:

- fundamental field definitions may drift from Morningstar
- point-in-time correctness may be weaker
- symbol mapping and corporate action handling must be validated explicitly
- Massive's deprecated experimental financials endpoint should not be used for new integrations; prefer the current `/stocks/financials/v1/*` endpoints and `v2/reference/news`

### Paper / Live Execution Mode

Execution adapters are isolated from the strategy layer. Paper mode is the required first live stage; live broker usage remains opt-in and explicitly warned.

## Fidelity Risk Register

The following items must be validated before claiming behavioural parity:

- `fundamental definitions`: ROE, gross margin, debt/equity, growth rates, PE, and PEG may not match provider formulas exactly
- `point-in-time accuracy`: late-restated filings can change historical values
- `symbol mapping`: ticker changes, delistings, and mergers require robust security master data
- `corporate actions`: splits and dividends must be reflected consistently in price history and holdings
- `survivorship bias`: alternative datasets often exclude dead symbols
- `live timing drift`: web APIs can lag compared with institutional feeds
- `rate limits`: external APIs can induce partial datasets or retries

## Validation Plan

1. Capture baseline QuantConnect backtest artefacts
2. Re-run locally with the same parameters
3. Compare:
   - monthly universe snapshots
   - ranked candidate tables
   - target weights
   - holdings transitions
   - order event timelines
4. Log all material deviations with the identified provider cause

## News and LLM Inputs

The advisory subsystem accepts curated text inputs through a separate ingestion abstraction. This prevents the core strategy from being tightly coupled to any specific news vendor and keeps the advisory layer defeatable.

## Massive Endpoint Notes

Current official Massive endpoint families relevant to this repository:

- `aggregates`: `/v2/aggs/ticker/...`
- `news`: `/v2/reference/news`
- `financial ratios`: `/stocks/financials/v1/ratios`
- `income statements`: `/stocks/financials/v1/income-statements`

The older experimental financials endpoint is deprecated by Massive and should not be used for fresh provider work.
