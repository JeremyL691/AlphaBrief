# Development Plan 0012: Quality Gates and Tooling Cleanup

## Goal

Bring the project quality gates into a runnable state before the next feature
development round.

## Changes

1. Configure Ruff to exclude `_reference_sources/` so reference material is not
   linted as AlphaBrief-owned code.
2. Run Ruff auto-fixes on AlphaBrief-owned `packages/` and `tests/` files.
3. Fix remaining Ruff issues in AlphaBrief-owned code.
4. Fix existing mypy issues in AlphaBrief-owned packages and tests.
5. Preserve Pydantic runtime validation tests while making invalid-input tests
   statically type-checkable.
6. Re-run pytest, Ruff, and mypy as full quality gates.

## Out of Scope

1. Any feature work for ModelGateway, research briefs, providers, RiskGate, or
   paper trading.
2. Any edits to `_reference_sources/`.
3. Any behavior change to live trading, broker adapters, or execution.
4. Any dependency installation or provider SDK setup.

## Acceptance

1. `python3 -m pytest` passes.
2. `.venv/bin/ruff check .` passes.
3. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passes.
