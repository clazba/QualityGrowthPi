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

### External Equivalent Mode

Use this mode when local QuantConnect-compatible data is unavailable.

Strengths:

- allows local development and partial validation
- can support operator workflows and advisory enrichment

Risks:

- fundamental field definitions may drift from Morningstar
- point-in-time correctness may be weaker
- symbol mapping and corporate action handling must be validated explicitly

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
