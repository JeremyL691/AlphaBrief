# Development Plan 0013: Model Registry and Provider Config MVP

## Goal

Add the minimal provider and model profile configuration boundary for Phase 2 so
future model-backed modules can select models by capability without hard-coding
provider SDK details.

## Changes

1. Add `alphabrief_models.registry`.
2. Define `ProviderConfig` for provider metadata and enabled state.
3. Define `ModelProfile` for model name, provider, capabilities, enabled state,
   and priority.
4. Define `ModelRegistry` for validating provider/profile references.
5. Add capability-based profile lookup and deterministic selection.
6. Export registry objects from `alphabrief_models`.
7. Add registry tests and documentation.

## Out of Scope

1. Real provider adapters or provider SDK dependencies.
2. Reading environment variables or loading secret values.
3. Retry, fallback, rate limits, pricing, or usage tracking.
4. Prompt template storage or structured output parsing.
5. Research brief generation, agents, order generation, RiskGate, PaperBroker,
   or live trading.
6. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_model_registry.py` passes.
2. Full pytest suite passes.
3. Ruff and mypy pass.
4. Disabled providers and disabled model profiles are excluded from selection.
5. Registry config stores env var names only and does not store secret values.
