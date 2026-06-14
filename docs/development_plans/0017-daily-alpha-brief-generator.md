# Development Plan 0017: DailyAlphaBrief Schema and Generator MVP

## Goal

Add the minimal Phase 2 daily research brief boundary by validating model
output as `DailyAlphaBrief` through `ModelGateway`.

## Changes

1. Add `DailyAlphaBrief` to research brief schemas.
2. Add `DailyBriefGenerationErrorCode`, `DailyBriefGenerationResult`, and
   `generate_daily_alpha_brief`.
3. Generate daily briefs only through `ModelGateway`.
4. Validate provider output with `parse_structured_output`.
5. Return structured failures for provider rejection, provider failure, and
   schema validation errors.
6. Export the new public API from `alphabrief_models`.
7. Add tests and documentation.

## Out of Scope

1. Real provider SDKs, network calls, or environment loading.
2. Prompt template storage or rendering.
3. Agent runtime, multi-model debate, retries, or persistence.
4. StrategySpec, Signal, OrderIntent, RiskDecision, or order generation.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_daily_alpha_brief.py` passes.
2. Full project tests pass.
3. Ruff and mypy pass.
4. The generator stores no raw prompt text, raw output text, API keys, or
   provider secrets.
