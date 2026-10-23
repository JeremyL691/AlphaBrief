# Changelog

All notable changes to AlphaBrief are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0-rc.7] - 2026-10-23

### Fixed
- A committee round ran inside the opportunity check and awaited the whole thing. With a reasoning model one round took over seventeen minutes, and while it ran the periodic check task recorded nothing: four runs in half an hour against a 180-second cadence. Since the soak evaluator counts those task runs as liveness, a slow round would have failed every day for a reason unrelated to correctness. The round now runs as its own task, and an in-flight round blocks a second one.
- The configured free model (`nvidia/nemotron-3-super-120b-a12b:free`) is still listed in the OpenRouter catalog but every completion returns HTTP 404 from the upstream provider, so no round could succeed while each attempt still consumed call allowance. Switched to `recursive/flint-v1.0:free`, verified with a real completion: zero cost, valid JSON, about 1.5s on a small prompt.

## [1.0.0-rc.6] - 2026-10-22

### Fixed
- The opportunity-round guards never bound anything: the runtime read `cycle_key` off a summary object that does not expose it, so the daily round cap and the minimum spacing always saw zero. One day recorded 95 rounds against a cap of 20, and a single UTC day reached 2015 model calls against the free channel's 1000-call ceiling.
- A failing model provider was retried on every scan until the day's whole call allowance was gone: roughly 1000 provider errors in three hours consumed the entire budget. Three consecutive failed rounds now open a channel breaker that stops escalation until a round succeeds again.

### Security
- The reviewed committee thresholds had been released (confidence floor `0.55` to `0`, analyst quorum `2` to `0`, the risk role's veto switched off, position cap `0.25` to `0.95`). They are restored, and `DisciplineSettings` now refuses any value looser than the reviewed numbers, so AGENTS 8.6 "risk values may only be tightened" is enforced by the loader instead of by convention. Tightening remains allowed.
- `escalate_on_flat` is off again: a day without a strategy signal spends zero model calls.

## [1.0.0-rc.5] - 2026-10-20

### Security
- The OANDA HTTP client logged the full account id on every retry and give-up line, because the request path carries it: one evening of TLS handshake timeouts wrote 3107 occurrences into `backend.err.log`. The path is now logged with the account segment masked (`NNN-***-***-NNN`), keeping the endpoint and failure class identifiable.

## [1.0.0-rc.4] - 2026-10-20

### Fixed
- The configuration loaders searched only the working directory, and the LaunchAgent starts the backend in the data directory. The process therefore ran on `ModelSettings()` defaults: primary channel `chatgpt_plan` instead of the reviewed `openrouter_free`, and a 150-call daily budget instead of the reviewed 1000. Both loaders now resolve the reviewed file from the repository root (or the packaged bundle) as well, and a relative path is anchored the same way.

## [1.0.0-rc.3] - 2026-10-20

### Added
- Continuous opportunity checks: during the FX session the runtime scans stored candles, strategy signals and broker facts every 1-5 minutes and only runs the full five-role committee when a signal clears every deterministic guard (confidence floor, daily round cap of 15, ten-minute spacing, model budget). This is the cadence PROJECT_GUIDE 5.1 specifies, and it replaces the three fixed decision rounds.
- `GET /api/v1/soak/status` and `GET /api/v1/models` read-only endpoints so the dashboard shows soak progress and model-channel budget from real facts.
- `alphabrief soak reset --reason` to supersede a failed soak run and open a new Day 0 while keeping the old run in the reset history.

### Fixed
- The resident runtime never registered the `ai_daily_cycle` task, so the soak evaluator counted zero opportunity rounds and could never qualify a day.
- The soak evaluator expected a round every five minutes on any weekday, contradicting the CURRENCY session (Monday 21:00 to Friday 21:00 UTC) and turning every healthy Monday into an extension.
- `market_sync` refreshed only the traded universe, letting the gold/S&P/oil signal series age past the two-hour quality limit and failing every symbol with `NO_TRADE_DATA_STALE`.
- `service install` wrote the OANDA token and account id into the LaunchAgent plist and left it world-readable (0644). The plist now carries no credential, is `0600`, and `service status` audits an existing one.
- The dashboard requested `/api/v1/ai-trading/*` and `/api/v1/risk/status`, none of which exist; the risk page also rendered hardcoded `50% / 150% / 5 per day` limits that had already drifted from the configuration.
- The committee page's cycle selector had no accessible name; axe now reports zero critical or serious violations again.

### Changed
- `pytest` no longer rewrites the committed screenshots under `docs/images/`; only `ALPHABRIEF_UPDATE_SCREENSHOTS=1` does.

## [1.0.0-rc.2] - 2026-10-14

### Changed
- Trading opportunity evaluation cadence updated to continuous unattended polling every 1–5 minutes throughout forex market hours, submitting OANDA practice orders only when high-confidence strategy rules and deterministic risk gates align.
- ModelGateway budget for OpenRouter free tier officially specified at 1,000 calls/day software limit with strict catalog zero-price enforcement, non-blocking fallback, and zero-fee guarantees.
- Clarified soak test qualification rules: single-day historical segment replays are strictly separated from continuous 14-calendar-day real-time practice soak testing.
- Re-enforced core safety invariants: live trading remains completely unreachable, and no trades are forced (`no_trade` is a first-class healthy result).

## [1.0.0-rc.1] - 2026-10-04

### Added
- Resident background daemon via macOS LaunchAgent (`ai.alphabrief.backend`) with automated recovery, single-instance process lock (`runtime.lock`), and per-account trading ownership lock.
- Packaged standalone desktop application bundle (`AlphaBrief.app`) and arm64 DMG installer (`AlphaBrief-1.0.0-rc.1-arm64.dmg`) built with PyInstaller and Electron.
- Full 14-day unattended soak test evaluator (`alphabrief soak status`, `alphabrief soak start`) computing day qualifications, downtime, extensions, and resets from database facts.
- Automated release soak report generator (`alphabrief report soak [--final]`) rendering detailed markdown and JSON reports per Project Guide Appendix D.
- Five-role AI Trading Committee (Macro, Fundamental, Technical, Risk, Portfolio Manager) with evidence citations, deterministic JSON schema enforcement, and repair loops.
- Model Gateway supporting ChatGPT subscription access ("Sign in with ChatGPT") and OpenAI-compatible pay-per-use key failover, constrained by daily call budgets.
- Deterministic RiskGate with 12 entry and sizing rules, NAV leverage caps, home currency conversions, and consecutive loss freezes.
- Emergency kill switch and automatic 5% NAV drawdown liquidation latch (`soak_halted`).
- OANDA v20 practice integration with two-way reconciliation (`BrokerReconStore`), at-most-once submission idempotency, and immediate freezing on unexplained discrepancies.
- Versioned DuckDB migrations (schema migrations 1 through 5) supporting transactional idempotency and verifiable audit ledgers.
- System health diagnostic suite (`alphabrief doctor run`) covering credentials, network connectivity, market data freshness, and execution lock states.
- Strategy signal runner with built-in trend/momentum models and backtesting engine (`alphabrief backtest run`) on real historical candles.
- Automated daily operational report generator (`alphabrief report daily`).

### Security
- Execution strictly bound to OANDA practice endpoints (`api-fxpractice.oanda.com`, `stream-fxpractice.oanda.com`); live URLs, production switches, and fallback mock brokers are absent.
- Strict token and account ID masking in all logs, status displays, telemetry, and exported reports.
- Comprehensive git history secret scanner (`scripts/secret_scan.py --history`) integrated into pre-commit and release verification gates.
