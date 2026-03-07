# LLM Advisory Subsystem

## Role

The LLM subsystem is an optional decision-support layer for:

- sentiment scoring
- narrative extraction
- contextual risk flags
- operator commentary

It is not an execution engine and cannot place orders directly.

## Provider Design

Default provider family:

- Gemini low-latency, cost-aware configuration through an adapter

Provider assumptions:

- model ID is configured externally
- fallback model is available through configuration
- request timeout, retry, and budget caps are enforced

## Input Discipline

Inputs are bounded and structured:

- curated text excerpts
- symbol identifiers
- deterministic strategy scores
- optional recent price context
- known event metadata

The system avoids unbounded prompt stuffing and records prompt template versions.

## Output Schema

Each advisory payload includes:

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

Rules:

- low confidence or sparse evidence forces `no_effect`
- malformed or unavailable output is ignored safely
- bounded risk modifiers are deterministic and capped in code
- every effect is logged with the original advisory record and policy outcome

## Auditability

Persist:

- prompt template version
- model name
- response hash
- parsed payload
- cache hit or miss
- downstream policy result

## Cost Control

- local cache with TTL
- per-day budget field
- batch sizing limits
- operator-visible report command
