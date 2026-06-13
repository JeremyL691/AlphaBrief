# Development Plan 0014: Repository Polish and Private GitHub Push

## Goal

Prepare the repository for a private GitHub push with clear English README,
safe ignore rules, and passing quality gates.

## Changes

1. Rewrite `README.md` for GitHub readability.
2. Document current MVP status, safety boundaries, setup, quality gates, and
   private availability.
3. Treat `_reference_sources/` as local-only material and exclude it from Git.
4. Update scaffold tests so the pushed repository does not require local
   reference-source checkouts.
5. Run pytest, Ruff, and mypy before commit.
6. Initialize Git locally if needed and push to the private GitHub repository.

## Out of Scope

1. Feature development.
2. Real provider adapters.
3. Any live trading, broker, RiskGate, or PaperBroker implementation.
4. Copying or pushing reference source code.
5. Publishing the repository publicly.

## Acceptance

1. `python3 -m pytest` passes.
2. `.venv/bin/ruff check .` passes.
3. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passes.
4. Git commit is created.
5. Remote GitHub repository remains private.
6. Branch is pushed to `https://github.com/JeremyL691/AlphaBrief.git`.
