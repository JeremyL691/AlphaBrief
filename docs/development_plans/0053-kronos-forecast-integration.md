# 0053 Kronos Forecast Integration

## Goal

Integrate Kronos as an optional AlphaBrief market-forecasting provider
that strengthens research and strategy evidence while keeping execution,
risk, and live-trading boundaries unchanged.

## Current Context

- AlphaBrief uses `ModelGateway` as the only supported model-call path.
- Research and strategy outputs are advisory until separately validated,
  backtested, and passed through risk controls.
- Kronos is an external financial-markets foundation-model project. It
  should be consumed through AlphaBrief-owned schemas and adapters, not
  copied or vendored.

## Files Changed

- `packages/alphabrief-models/src/alphabrief_models/gateway.py`
- `packages/alphabrief-models/src/alphabrief_models/kronos.py`
- `packages/alphabrief-models/src/alphabrief_models/__init__.py`
- `packages/alphabrief-models/src/alphabrief_models/evaluation_datasets.py`
- `apps/api/src/alphabrief_api/routes/models.py`
- `apps/cli/src/alphabrief_cli/model_commands.py`
- `pyproject.toml`
- `tests/test_kronos_integration.py`
- `tests/test_model_gateway.py`
- `tests/test_models_api.py`
- `tests/test_model_cli.py`
- `docs/model_gateway.md`
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/development_log.md`

## Modules Not Touched

- `alphabrief-risk`
- `alphabrief-execution`
- `alphabrief-backtest`
- Broker adapters
- Paper trading order routes
- `_reference_sources`

## Implementation Steps

1. Add `market_forecast` and `time_series_forecasting` to the model
   type system.
2. Add AlphaBrief-owned Kronos request/report/evidence schemas.
3. Add a `KronosForecastAdapter` that implements the existing
   `ProviderAdapter` contract.
4. Add runtime seams:
   - fail-closed unavailable runtime
   - deterministic CI/runtime smoke test path
   - wrapper for an operator-initialized external predictor
5. Add API and CLI forecast surfaces that run through `ModelGateway`.
6. Add routing/evaluation dataset metadata.
7. Add tests and docs.

## Tests

- Targeted pytest for model gateway, Kronos integration, API, and CLI.
- Ruff on changed source/test files.
- Mypy on changed source/test files.

## Risk Notes

- Forecasts are `advisory_only`.
- No signal, order intent, risk decision, or broker call is created.
- Real Kronos inference remains optional and operator-configured.
- Deterministic runtime is not a model-backed forecast.
- No external source code was copied.

## Done When

- Forecasts can be invoked through CLI and API.
- Gateway call records are produced.
- Failure without configured runtime is explicit.
- Tests, lint, type checks, and docs are complete.
