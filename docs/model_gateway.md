# AlphaBrief ModelGateway

ModelGateway is the only supported path for model calls.

## Principles

1. Business modules must not call provider SDKs directly.
2. Model selection is capability-based, not hard-coded by provider name.
3. Model outputs used by important workflows must be structured and validated.
4. Model call records must avoid secrets and support audit review.
5. Provider failures must be handled without bypassing risk controls.

## Future Responsibilities

1. Unified request and response schemas.
2. ProviderAdapter interface.
3. Model registry and capabilities.
4. Prompt template versioning.
5. Structured output validation.
6. Usage, latency, cost, and error logging.
7. Fallback and retry policy.

## Current MVP Contract

`alphabrief_models` implements the first runtime ModelGateway boundary.

Current objects:

1. `ModelRequest`: validated request ID, task type, prompt version, input text,
   required capabilities, and non-secret string metadata.
2. `ModelResponse`: provider response carrying output text and optional
   structured output.
3. `ModelCallRecord`: audit-oriented call metadata with input and output hashes,
   provider, model, task type, prompt version, latency, status, and error type.
4. `ProviderAdapter`: protocol that real and fake providers must satisfy.
5. `ModelGateway`: capability-based provider selector and call recorder.
6. `FakeProviderAdapter`: deterministic test adapter with success and failure
   modes.
7. `ProviderConfig`: provider metadata and enabled state.
8. `ModelProfile`: model metadata, capabilities, enabled state, and priority.
9. `ModelRegistry`: provider/profile validation and capability lookup.

Current behavior:

1. Providers are selected by required capabilities.
2. Requests are rejected when no provider satisfies the required capabilities.
3. Provider failures are recorded as failed calls without persisting raw provider
   error messages.
4. Call records store hashes instead of raw prompt text or raw output text.
5. The gateway keeps in-memory call records for tests and local development.
6. The registry selects enabled model profiles whose enabled providers satisfy
   requested capabilities.
7. Lower numeric model profile priority is selected first, with profile ID as a
   deterministic tie-breaker.
8. Provider config may store environment variable names for future adapters but
   does not read or store secret values.

## Current Non-Goals

1. No real provider SDK or network integration is implemented.
2. No API key or secret fields are added.
3. No retry, fallback, rate limiting, usage pricing, or prompt template storage
   is implemented.
4. No environment variable loading or real provider adapter instantiation is
   implemented.
5. No research brief, agent runtime, strategy generation, order generation, or
   execution behavior is implemented.
