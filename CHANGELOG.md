# Changelog

All notable changes to AlphaBrief are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
