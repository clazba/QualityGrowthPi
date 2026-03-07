# Data Providers

## Provider Plan In Practice

The repo uses different providers for different jobs.

Validated default roles:

- backtests: `QuantConnect cloud`
- paper deployment: `QuantConnect cloud + Alpaca brokerage`
- local fallback stack: `Massive + SEC + Alpaca + Alpha Vantage`
- LLM advisory provider: `Gemini`

This separation is deliberate. It keeps the strategy-validation path close to the original QuantConnect implementation while still giving the operator local data and reporting tools.

## Source Of Truth vs Fallbacks

### Source Of Truth For Strategy Validation

Use QuantConnect cloud when you care about:

- backtest fidelity
- dynamic fundamental universe behavior
- the validated paper deployment path

This is the current default and recommended path.

### Local Fallbacks For Operator Work

Use the local fallback providers when you care about:

- inspecting current paper holdings locally
- enriching the operator workflow with news and narrative context
- researching outside the cloud execution path
- preparing for an optional later local approximation path

Do not treat the local fallback stack as a strict parity replacement for QuantConnect cloud.

## Provider Roles

### QuantConnect Cloud

Used for:

- cloud backtests
- cloud paper deployment
- QuantConnect-hosted live and historical data in the first paper stage

Strengths:

- closest behavior to the original strategy
- no local LEAN dataset downloads required for normal cloud backtests
- least operator burden for initial paper deployment

Trade-off:

- the execution host is remote, not fully on-prem

### Alpaca

Used for:

- paper brokerage execution
- local inspection of account and current positions
- local fallback daily bars

Strengths:

- clean paper brokerage API
- simple account and positions inspection
- useful daily-bar source for local operator tooling

Trade-off:

- not a full replacement for QuantConnect's fundamental and universe data stack

### Massive

Used for:

- local fallback news
- local fallback aggregates
- local fallback financial ratios and income statements

Strengths:

- broad structured market-data surface
- useful for operator review and approximation workflows

Trade-off:

- still not exact Morningstar or QuantConnect parity

Current endpoint families used or scaffolded:

- aggregates: `/v2/aggs/ticker/...`
- news: `/v2/reference/news`
- ratios: `/stocks/financials/v1/ratios`
- income statements: `/stocks/financials/v1/income-statements`

The old experimental financials endpoint should not be used.

### Alpha Vantage

Used for:

- local fallback news
- local fallback fundamentals
- redundancy in the operator workflow

Strengths:

- inexpensive supplemental data source
- useful for news, narrative, and lightweight fallback enrichment

Trade-off:

- limited parity with the QuantConnect fundamental pipeline

### SEC

Used for:

- local fallback fundamentals validation
- public-data support in the approximation stack

Strengths:

- free and public
- useful for validating and reconstructing fundamentals locally

Trade-off:

- requires normalization and does not reproduce QuantConnect point-in-time handling directly

### Gemini

Used for:

- structured advisory generation in the operator workflow
- schema-shaped narrative review of current paper candidates

Strengths:

- integrates into the saved operator workflow and `make llm-report`
- provides a secondary narrative lens for active candidates

Trade-off:

- not part of the deterministic signal engine
- advisory output is only useful when schema validation succeeds and recent news is available

## Operator Workflow News Stack

`make workflow` does not rely on a single news source.

Current behavior:

1. use the configured news provider first
2. if the runtime provider is not already composite, add operator-side fallback providers
3. merge and deduplicate recent news events across:
   - local file cache
   - Alpha Vantage
   - Massive

This matters because your runtime config may still say `NEWS_PROVIDER_MODE=file`, but the operator workflow should make best-effort use of online providers when reviewing current paper symbols.

## Main Drift Risks Outside QuantConnect Cloud

These are the main reasons local results can diverge from the validated cloud path:

- different fundamental field definitions
- different point-in-time update timing
- ticker mapping and symbol-change behavior
- splits and dividend treatment
- survivorship differences
- provider API latency, gaps, and rate limits

## Practical Recommendation

Use QuantConnect cloud when:

- validating changes
- capturing new baselines
- running the first paper deployment

Use the local fallback stack when:

- you want operator-side research
- you need narrative context for current paper holdings
- you want approximation without buying local parity-grade LEAN datasets
