# LLM Advisory Subsystem

## Role In The System

The LLM is a secondary review layer, not the strategy engine.

It is used to:

- read recent news for current paper candidates
- generate structured sentiment and risk commentary
- suggest `no_effect`, `caution`, `manual_review`, or `reduce_size`
- save advisory history for operator review

It is not used to:

- build the fundamental universe
- rank candidates
- apply timing filters
- create monthly target weights
- place orders directly

## Default Mode

The default mode is:

- `observe_only`

In this mode:

- advisories are generated and stored when possible
- advisories appear in the workflow report and `make llm-report`
- advisories do not change orders or target weights

## Workflow Integration

The LLM is integrated into `make workflow`.

When you run the workflow, it:

1. loads the latest backtest diagnostics
2. loads the current Alpaca paper positions
3. treats those symbols as the candidate set for narrative review
4. loads recent news for those symbols
5. runs advisory evaluation
6. stores results in SQLite
7. writes an LLM summary JSON and includes the results in the markdown workflow report

After that:

- `make llm-report` reads the saved advisory history from SQLite

## Provider And Prompting

Current default provider:

- Gemini

Current behavior:

- Gemini is asked for schema-shaped JSON output
- prompt templates live under `config/prompts/`
- the adapter and schema layer attempt conservative repair of common alias-style fields such as `confidence` and `reasoning`

Why this matters:

- models can still return partial JSON even when instructed not to
- only schema-valid payloads become saved advisories

## Output Fields

Saved advisory payloads normalize to:

- `symbol`
- `sentiment_score`
- `sentiment_label`
- `confidence_score`
- `key_catalysts`
- `key_risks`
- `narrative_tags`
- `event_urgency`
- `suggested_action`
- `rationale_short`
- `source_coverage_score`
- `model_name`
- `prompt_version`

## Safety Policy

Supported modes:

- `disabled`
- `observe_only`
- `advisory_only`
- `risk_modifier`

Important safety rules:

- malformed responses fail open
- low confidence or low source coverage blocks influence
- `reduce_size` is bounded and deterministic
- manual-review flags are explicit
- the LLM never submits orders

## How Operators Should Use It

Treat LLM output as:

- narrative context
- recent-news interpretation
- a manual review aid

Do not treat it as:

- the primary stock selector
- a replacement for backtest diagnostics
- an autonomous trading engine

Normal operator commands:

```bash
make workflow
make llm-report
```

Useful outputs:

- `results/opportunities/llm_workflow_latest.json`
- SQLite advisory history via `make llm-report`

## Known Limits

- the LLM currently reviews current paper candidates, not the full ranked candidate universe
- if no recent news is found, no advisory records are created
- if Gemini credentials are missing, the workflow reports the provider as unavailable
- if model output still fails schema validation, advisories are not saved
