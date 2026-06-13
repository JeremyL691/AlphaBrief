# Development Plan 0011: ModelGateway Contract and FakeProvider MVP

## Goal

Start Phase 2 by implementing the smallest model-call boundary for AlphaBrief.
All future model-backed modules must call providers through ModelGateway instead
of directly using provider SDKs.

## Changes

1. Add `alphabrief_models` under `packages/alphabrief-models/src`.
2. Define `ModelRequest`, `ModelResponse`, `ModelCallRecord`, and
   `ModelGatewayResult`.
3. Define the `ProviderAdapter` protocol used by `ModelGateway`.
4. Implement a deterministic `FakeProviderAdapter` for tests and local
   development.
5. Implement capability-based provider selection in `ModelGateway`.
6. Record each attempted model call with input and output hashes instead of raw
   prompt or raw output text.
7. Reject requests when no provider satisfies the requested capabilities.
8. Record provider failures without persisting provider error messages that may
   contain sensitive data.
9. Update project configuration, tests, and documentation.

## Out of Scope

1. Real provider adapters or provider SDK dependencies.
2. API keys, `.env` changes, network calls, retries, or fallback policy.
3. Prompt template version storage beyond the request field.
4. Structured output schema parsing beyond carrying an optional structured
   output payload.
5. Research brief generation, agents, daily reports, strategy generation, or
   any execution behavior.
6. RiskGate, PaperBroker, order routing, portfolio state, or live trading.
7. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_model_gateway.py` passes.
2. Full pytest suite passes.
3. `alphabrief_models` can be imported from the configured package path.
4. Every gateway invocation returns a `ModelCallRecord`.
5. `ModelCallRecord` contains hashes and metadata only, not raw prompt, raw
   output, API keys, or secrets.
6. No real provider SDK is introduced.
