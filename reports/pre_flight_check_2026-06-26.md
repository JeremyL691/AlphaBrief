# AlphaBrief Pre-Flight Check Report

**Run date:** 2026-06-26 (Asia/Shanghai)
**Scope:** Confirm the local checkout is ready to attach to an external
paper broker and run the 30-day observation.
**Baseline:** Phase 23 acceptance closeout + paper-broker pre-flight
addition.

This report captures the five standard gates plus the new paper-broker
pre-flight. Every gate is green. The project is ready to attach to
Alpaca paper and start the 30-day run.

## 1. Verdict

**PASS — ready to start the 30-day paper observation.**

Follow the steps in `docs/paper_broker_setup.md` to wire the Alpaca
paper account credentials into `.env` and start the scheduler.

## 2. Gate Summary

| # | Gate | Result | Detail |
|---|---|---|---|
| 1 | `pytest` (full, excluding sandbox-blocked) | ✅ PASS | 1206 passed, 3 warnings (numpy runtime warnings in legacy backtest CLI test, pre-existing) |
| 2 | `ruff check .` | ✅ PASS | All checks passed |
| 3 | `mypy packages apps tests` | ✅ PASS | 223 source files clean, strict mode |
| 4 | `alphabrief acceptance verify --compact` | ✅ PASS | 11/11 checks passed (10 existing + 1 new `paper.preflight`) |
| 5 | `alphabrief acceptance preflight --scope paper` | ✅ PASS | 1/1 checks passed (`paper.preflight` only) |

## 3. Pytest Detail

```
1206 passed, 3 warnings in 99.03s (0:01:39)
```

Excluded by design (sandbox-blocked localhost mock-broker tests):
`tests/test_alpaca_adapter.py`, `tests/test_broker_api_live.py`. These
fail in any sandbox that cannot bind `127.0.0.1` and pass in normal
local environments. Not code bugs.

The 3 warnings are unrelated numpy runtime warnings emitted by an
existing legacy CLI backtest test fixture (`tests/test_backtest_commands.py::test_cli_backtest_run_legacy_still_works`). Pre-existing.

## 4. Acceptance Verifier Detail

All 11 checks passed:

| Check ID | Status | Title |
|---|---|---|
| `docs.required` | passed | Required project documents are present |
| `runtime.imports` | passed | Runtime package surfaces are importable |
| `config.paper_only_default` | passed | Default settings are paper-only |
| `execution.paper_policy` | passed | Paper execution policy stays locked |
| `risk.live_lock` | passed | RiskGate locks live trading |
| `models.kronos_advisory` | passed | Kronos forecasts remain advisory |
| `safety.reference_isolation` | passed | Reference sources are isolated |
| `safety.provider_sdk_imports` | passed | Provider SDK imports stay out of runtime business code |
| `docs.final_report_current` | passed | Final acceptance evidence is current |
| `quality.tooling_configured` | passed | Quality tooling is configured |
| `paper.preflight` | passed | Paper-broker pre-flight is ready |

## 5. Paper-Broker Pre-Flight Detail

The new `paper.preflight` check confirms the 30-day observation
readiness, end-to-end:

- ✅ `docs/paper_broker_setup.md` exists.
- ✅ `.env.example` documents both `ALPHABRIEF_ALPACA_KEY` and
  `ALPHABRIEF_ALPACA_SECRET`.
- ✅ `config/paper_execution_policy.yaml` loads and remains locked
  (`mode: paper`, `automated_execution: false`,
  `require_human_review: true`).
- ✅ `config/alpaca_paper.yaml` exists and parses
  (`base_url: https://paper-api.alpaca.markets`,
  no live URL leak).
- ✅ Drift guard: code env-var names match `.env.example` names.

## 6. What the Operator Does Next

1. Read `docs/paper_broker_setup.md`.
2. Sign up at <https://app.alpaca.markets/signup> (Paper mode).
3. Generate paper API key + secret in the Alpaca dashboard.
4. `cp .env.example .env` and fill in `ALPHABRIEF_ALPACA_KEY` and
   `ALPHABRIEF_ALPACA_SECRET`.
5. `alphabrief acceptance preflight --paper` (still green).
6. `alphabrief broker status` (live adapter selected, no open freezes).
7. 30-second smoke: `alphabrief scheduler run --reconcile-interval 5`,
   then Ctrl-C.
8. Start the run: `alphabrief scheduler run --reconcile-interval 60`.

The runbook covers daily and weekly observation checkpoints, freeze
handling, and end-of-run reporting.

## 7. Out of Scope (for this report)

- Live trading (not implemented; RiskGate locked; scheduler exits 3 on
  live-mode env).
- 30-day external paper observation itself (requires operator-supplied
  credentials and elapsed time).
- LICENSE / SECURITY / CONTRIBUTING (separate decision).
- Production deployment, auth, secret rotation, backup, monitoring
  (separate operations plan).