# Development Plan 0001: Repository Scaffold

## Goal

Create AlphaBrief's first repository scaffold and safety rules without
implementing runtime business logic.

## Changes

1. Rename `Source projects/` to `_reference_sources/`.
2. Add project rules and agent instructions.
3. Add README and architecture/risk/model/rewrite roadmap document shells.
4. Add empty top-level implementation directories with `.gitkeep` files.
5. Add a minimal `pyproject.toml`.
6. Add scaffold tests that verify required files, directories, reference-source
   isolation, and the default live-trading lock in `.env.example`.

## Out of Scope

1. Domain models.
2. Market data loaders.
3. StrategySpec or backtesting.
4. RiskGate or PaperBroker implementation.
5. Real model providers.
6. CLI, API, or dashboard runtime.

## Acceptance

1. `pytest tests/test_project_scaffold.py` passes.
2. `ruff check .` passes when ruff is installed.
3. The repository contains the documented scaffold and no AlphaBrief code
   imports reference sources.
