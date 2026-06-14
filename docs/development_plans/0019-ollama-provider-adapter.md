# Development Plan 0019: Ollama Provider Adapter MVP

## Goal

Complete the Phase 2 requirement for at least one real provider adapter without
adding cloud SDK dependencies or secrets.

## Changes

1. Add `OllamaProviderAdapter`.
2. Implement the existing `ProviderAdapter` protocol.
3. Call a local Ollama server through standard-library HTTP at `/api/generate`.
4. Use non-streaming responses.
5. Request JSON format when structured output is required.
6. Parse Ollama responses into `ModelResponse`.
7. Map HTTP, connection, and invalid response failures to `ModelProviderError`.
8. Export the adapter from `alphabrief_models`.
9. Add tests and documentation.

## Out of Scope

1. Cloud provider SDKs or API keys.
2. Environment variable loading or adapter factory construction.
3. Streaming responses, retries, fallback, rate limits, or cost accounting.
4. Prompt template changes, agent runtime, RiskGate, or execution behavior.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_ollama_provider_adapter.py` passes.
2. Full project tests pass.
3. Ruff and mypy pass.
4. ModelGateway records Ollama success and failure paths.
