# Development Plan 0003: Core Configuration System MVP

## Goal

Implement the minimal AlphaBrief configuration entry point for environment,
logging, live-trading lock state, and local storage paths.

## Changes

1. Add `alphabrief_core.config`.
2. Add `AlphaBriefEnv`, `LogLevel`, `AppSettings`, and `load_settings`.
3. Load only known `ALPHABRIEF_` environment variables.
4. Keep `ALPHABRIEF_LIVE_TRADING_ENABLED` defaulted to `false`.
5. Parse booleans only from explicit values: `true/false`, `1/0`, `yes/no`,
   and `on/off`.
6. Add path settings for local data, generated reports, and audit logs.
7. Export configuration types from `alphabrief_core`.
8. Add configuration tests and update `.env.example`.

## Out of Scope

1. Reading `.env` files.
2. CLI, API, data loading, model providers, brokers, RiskGate, or PaperBroker.
3. API keys, broker keys, provider secrets, or secret manager integration.
4. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py`
   passes.
2. `ruff check .` passes if ruff is installed.
3. `python3 -m mypy packages/alphabrief-core/src tests` passes if mypy is
   installed.
