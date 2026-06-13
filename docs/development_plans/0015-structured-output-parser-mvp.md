# Development Plan 0015: Structured Output Parser MVP

## Goal

Add the minimal structured output validation boundary for Phase 2 so future
research modules can rely on Pydantic-validated model outputs without parsing
JSON themselves or trusting free-form text.

## Changes

1. Add `alphabrief_models.structured_output`.
2. Define `StructuredOutputErrorCode` (StrEnum) with stable error code values.
3. Define `StructuredOutputResult[TargetModel]` to carry a parsed target or a
   structured failure without raising.
4. Define `parse_structured_output(response, target)` for Pydantic target
   models.
5. Prefer `ModelResponse.structured_output` when available; fall back to JSON
   parsing of `output_text` when requested.
6. Reject empty output, invalid JSON, non-mapping JSON, and schema mismatches
   with explicit error codes.
7. Allow tests to inject a JSON decoder but do not read environment variables
   or call provider SDKs.
8. Add structured output tests and documentation.

## Out of Scope

1. Real provider adapters, network calls, or environment variable loading.
2. Retries, fallback, rate limits, or pricing.
3. Research brief generation, agents, order generation, RiskGate, or
   PaperBroker.
4. Any implementation copied from `_reference_sources/`.
5. Storing raw prompt, raw output, or secret values inside parser results.

## Acceptance

1. `tests/test_structured_output.py` passes.
2. Full pytest suite passes.
3. Ruff and strict mypy pass.
4. The parser never raises for malformed model output.
5. Error codes are stable across versions.
