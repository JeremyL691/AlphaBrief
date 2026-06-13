# Development Plan 0016: MarketBrief and SymbolBrief Schemas MVP

## Goal

Add the minimal research brief schemas for Phase 2 so future research layer
work can produce and validate structured market and symbol briefs without
defining its own Pydantic types.

## Changes

1. Add `alphabrief_models.briefs`.
2. Define `MarketBrief` with required identity, timezone-aware `generated_at`,
   `trading_day`, `regime`, `summary`, `confidence`, and `key_factors`.
3. Define `SymbolVerdict` with `direction`, `confidence`, and `rationale`.
4. Define `SymbolBrief` with required identity, `symbol`, `generated_at`,
   `horizon`, `verdict`, `catalysts`, and `risks`.
5. Define typed literal aliases for regime, direction, and horizon.
6. Export the new schemas from `alphabrief_models`.
7. Add brief schema tests including integration with
   `parse_structured_output`.
8. Update model gateway docs, architecture, roadmap, development log, and
   README.

## Out of Scope

1. Brief generation logic or research layer runtime.
2. Real provider adapters, network calls, or environment variable loading.
3. Retries, fallback, rate limits, or pricing.
4. RiskGate, PaperBroker, order generation, or execution behavior.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_brief_schemas.py` passes.
2. Full pytest suite passes.
3. Ruff and strict mypy pass.
4. The schemas are valid targets for `parse_structured_output`.
5. The schemas do not call providers, read environment variables, or produce
   side effects.
