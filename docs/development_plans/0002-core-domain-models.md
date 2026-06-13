# Development Plan 0002: Core Domain Models MVP

## Goal

Implement the minimal AlphaBrief core domain schemas needed by future data,
strategy, risk, and execution modules.

## Changes

1. Add `packages/alphabrief-core/src/alphabrief_core/`.
2. Add Pydantic v2 models for `Bar`, `Signal`, `OrderIntent`,
   `RiskDecision`, and `Order`.
3. Add Literal type aliases for signal direction, order intent source, order
   side, and order type.
4. Add validations for forbidden extra fields, non-empty strings,
   timezone-aware datetimes, Decimal-only financial values, confidence range,
   OHLCV consistency, order-intent sizing, limit price rules, and order risk
   decision linkage.
5. Update `pyproject.toml` with the `pydantic` runtime dependency, package
   discovery, pytest pythonpath, and mypy file scope.
6. Add focused domain model tests.
7. Update architecture and development log documentation.

## Out of Scope

1. `ResearchBrief` and `ModelCallRecord`.
2. StrategySpec, market data providers, data loaders, and backtesting.
3. RiskGate, RiskLimit, KillSwitch, PaperBroker, and OrderRouter.
4. Real broker adapters or model providers.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py`
   passes.
2. `ruff check .` passes if ruff is installed.
3. `python3 -m mypy packages/alphabrief-core/src tests` passes if mypy is
   installed.
