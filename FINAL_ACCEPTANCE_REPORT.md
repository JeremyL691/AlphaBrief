# AlphaBrief Final Acceptance Report

**Audit date:** 2026-07-10 (Asia/Shanghai)
**Audit object:** `JeremyL691/feat/oanda-paper-defaults` after Round 0063
OANDA-first default-paper alignment.
**Baseline:** latest local quality gates and the read-only broker-status check.

This report is both the final local code acceptance summary and the
remaining operational gate list. It does not claim completion of
external account operations that require broker credentials and elapsed
time.

## 1. Executive Conclusion

AlphaBrief is locally complete as a paper-first research, backtesting,
risk, execution-simulation, broker-paper integration, and review
workbench. The current checkout includes:

- core market data, news, macro, model, strategy, backtest, gym,
  research, review, risk, execution, API, CLI, and dashboard surfaces;
- OANDA v20 practice as the default paper-broker path, with a 19-instrument
  multi-asset policy spanning FX, metals, and selected index CFDs; Alpaca
  remains an optional compatibility path;
- default scheduler FX universe aligned to `EUR_USD`, `GBP_USD`, and
  `USD_JPY`;
- optional Kronos market forecasts through `ModelGateway`, structured
  and advisory only;
- Phase 23 `alphabrief_acceptance` verifier exposed through
  `alphabrief acceptance verify` and
  `GET /api/v1/acceptance/verify`.

The project remains paper-only. Live trading is disabled by default and
locked by `RiskGate` when `live_trading_enabled=True`. There is no
completed 30-60 day external paper-account observation record in this
repository, because that gate requires user-provided broker credentials,
an external paper account, and elapsed operating time.

## 2. Evidence Summary

| Verification item | Status | Evidence |
|---|---|---|
| Round 0063 full pytest | Passed | 1361 tests passed; 9 known warnings |
| Round 0063 static quality gates | Passed | `ruff check .`, strict Mypy across 253 source files, and `git diff --check` passed |
| Round 0063 acceptance verifier | Passed | `alphabrief acceptance verify --compact`: 11/11 |
| Default paper policy | Passed | OANDA practice, 19 instruments, human review, and disabled automation |
| Read-only broker status | Passed | Latest reconciliation matched; zero open freezes |
| Default live trading lock | Passed | `load_settings({}).live_trading_enabled` remains false |
| Execution policy | Passed | Default OANDA-practice multi-asset policy stays paper-mode, human-review, and no-automation |
| RiskGate live lock | Passed | Acceptance check verifies `live_trading_locked` rejection when live mode is forced on |
| Kronos boundary | Passed | Forecasts run through `ModelGateway` and validate as `advisory_only=True` |
| Reference-source isolation | Passed locally | Acceptance verifier scans runtime imports under `apps/` and `packages/` |
| Provider SDK boundary | Passed locally | Acceptance verifier scans runtime business imports for direct SDK use |
| External paper-account operations | Not started | OANDA practice credentials and read-only account status were verified; no order-capable AI command or 30-day observation was started |
| Live trading | Not implemented and locked | No live adapter is delivered; RiskGate rejects live-mode configurations |

The latest quality gate is tracked in `docs/roadmap.md` and
`docs/development_log.md`. This report intentionally separates local
code acceptance, read-only broker evidence, and broker-account operating
evidence.

## 3. Implemented Product Scope

### Data and Research

- CSV and Parquet OHLCV loading, DuckDB persistence, data quality
  checks, and no-lookahead feature helpers.
- Yahoo Finance, Binance, Alpha Vantage, RSS/Atom, SEC EDGAR, FRED, and
  simulated sentiment provider boundaries with retry and test seams.
- `ModelGateway`, provider adapter contracts, model registry, prompt
  versioning, structured output parsing, model evaluation, model
  performance persistence, and routing advice.
- Local Ollama adapter, fake providers for tests, MarketBrief,
  SymbolBrief, DailyAlphaBrief, multi-model debate, and consensus
  aggregation.
- Kronos market forecasts as advisory research artifacts only.

### Strategy, Backtest, and Simulation

- `StrategySpec`, strategy interfaces, moving-average sample strategy,
  external evidence declarations, and signal evidence.
- Persistent strategy specifications and signal history.
- Vectorized long/flat backtesting with fees, slippage, equity curves,
  trades, returns, drawdown, trade count, and win rate.
- Gym-style trading environments with discrete and continuous actions,
  multi-asset support, optional shorting, leverage, borrow costs,
  liquidity limits, market impact, and pluggable rewards.

### Risk and Execution

- Mandatory `OrderIntent -> RiskGate -> RiskDecision -> broker`
  boundary.
- Risk checks for trading enabled flag, live lock, strategy and symbol
  allowlists, quantity, order notional, data quality, manual review,
  kill switch, total account exposure, per-symbol exposure,
  concentration, leverage, price deviation, market-open state, signal
  age, duplicate orders, daily loss, and drawdown floor.
- Checks are fail-closed when configured context is missing and
  tighten-only when they compute a `max_quantity` clamp.
- Internal paper broker, order router, fill simulator, portfolio state,
  execution audit log, and persistent paper route.
- Paper-only broker adapters (OANDA practice by default; Alpaca optional),
  order mapping, account and position reads, reconciliation storage,
  scheduler heartbeat, alerts, freeze controls, and CLI/API observation
  surfaces.

### Product Surfaces

- FastAPI routes for health, status, data, backtest, research, models,
  strategy, risk, internal paper trading, broker observation, scheduler,
  review, dashboard, and acceptance verification.
- Typer CLI commands for data, backtest, briefs, debate, model
  evaluation/routing/Kronos forecast, strategy management, risk checks,
  broker observation, scheduler operations, serving, and acceptance
  verification.
- Read-only dashboard pages for local observation. The dashboard does
  not unlock live trading or bypass `RiskGate`.

## 4. Project-Level Definition of Done

| Capability | Local status | Remaining operational gate |
|---|---|---|
| Reproducible research | Implemented locally | Production data/version governance still needs operator policy |
| Strategy admission | Partially implemented | Full audited workflow from backtest approval to paper deployment remains a future gate |
| Backtest credibility | Partially implemented | Benchmark, CAGR, Sharpe, Sortino, turnover, exposure, walk-forward, and overfit audit are still future hardening |
| Model reliability | Implemented as local gateway boundary | Production provider fallback, budgets, and cloud credentials remain operator-controlled |
| External paper adapter | Implemented locally | Real account submit/query/cancel/fill/reconcile exercise still needs credentials |
| Automated paper operations | Control plane implemented | 30-60 day continuous external paper observation still not complete |
| Account-level risk | Implemented locally | Production limits must be configured and reviewed per deployment |
| Security and operations | Partially implemented | Auth, secret rotation, backup, monitoring, and disaster drills need deployment evidence |
| Controlled live trading | Not implemented | Requires separate plan, credentials, review, kill switch, and external paper evidence |

## 5. Hard Safety Principles

1. Models are research tools, not execution authorities.
2. All model calls must go through `ModelGateway`.
3. Model output, UI state, natural-language input, and strategy
   registry flags cannot approve or relax risk.
4. Every order intent must pass deterministic `RiskGate` checks before
   paper execution.
5. Risk checks can reject, require review, or reduce size. They cannot
   unlock live trading.
6. External paper accounts are operating validation environments, not
   proof that live trading is safe.
7. Live trading requires a separate implementation and manual
   acceptance round after stable external paper operations.

## 6. Phase 23 Acceptance Verifier

The acceptance verifier is deliberately read-only. It inspects local
files and deterministic in-process contracts:

- required documents exist;
- runtime package surfaces import;
- default settings are paper-only;
- paper execution policy remains locked;
- `RiskGate` rejects live-mode configuration;
- Kronos forecast reports are structured and advisory-only through
  `ModelGateway`;
- runtime code does not import `_reference_sources`;
- runtime business code does not import provider SDKs directly;
- final acceptance evidence mentions the current Phase 23/Kronos
  boundary;
- pytest, Ruff, Mypy, and the acceptance package are configured.

It never calls brokers, broker SDKs, external market-data providers,
model providers, model weights, order routes, scheduler execution, or
live endpoints.

Run it locally with:

```bash
alphabrief acceptance verify --compact
```

Or through the API:

```text
GET /api/v1/acceptance/verify
```

## 7. Not Claimed As Complete

The following remain outside the local code closeout:

- external paper-account credentials and external paper-account operation;
- real submit/query/cancel/fill/reconcile drills against a user-owned
  paper account;
- daily and weekly operating reports from a continuous 30-60 day paper
  observation window;
- production authentication, deployment, alerting, backup, and secret
  rotation evidence;
- live trading adapter, live credentials, live endpoint access, or live
  order routing.

These are not small code leftovers. They are operational acceptance
gates that require a real environment and time.

## 8. Final Recommendation

Treat the current AlphaBrief checkout as ready for local paper-first
research and controlled OANDA-practice onboarding. The next real gate is
operational: run the existing adapter and scheduler under explicit limits,
retain daily reconciliation evidence, and only after 30-60 stable days
consider a separate live-trading design review.
