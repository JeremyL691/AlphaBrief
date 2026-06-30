# AlphaBrief Paper Broker Setup

This runbook is the operator-facing checklist for attaching AlphaBrief to
an external paper-trading broker and running a 30-day observation.

It assumes the local code is already installed (`pip install -e ".[dev]"`
in `.venv`) and that all standard quality gates pass.

## 1. What This Is For

A 30-day continuous observation against an external paper-trading account
(OANDA v20 demo/practice or Alpaca Paper). The goal is **not** to prove
that paper trading works in isolation — the internal paper broker already
does that. The goal is to verify, in a real external environment, that:

- the reconciliation snapshot pipeline is stable over time,
- `RiskGate` reject behavior matches what the unit tests assert,
- the scheduler survives restarts, signal traps, and slow cycles,
- secrets stay secret (never logged, never written to disk),
- live-trading locks cannot be bypassed by accident.

## 2. Prerequisites

- Python 3.12+ with the project virtual environment installed.
- One external paper-trading account:
  - **OANDA v20 demo/practice** — sign up at <https://www.oanda.com/>,
    create a demo account, generate a personal access token, and copy the
    demo account ID. This is the recommended path when Alpaca identity
    verification is unavailable.
  - **Alpaca Paper** — sign up at <https://app.alpaca.markets/signup>,
    stay in **Paper** mode, then generate a paper API key + secret from
    *View → API Keys → Generate Paper Key*.
- If both OANDA and Alpaca credentials are set, AlphaBrief prefers OANDA.
- All standard quality gates green:

  ```bash
  .venv/bin/alphabrief acceptance verify --compact
  # Expected: 11/11 checks passed.
  ```

## 3. One-Time Setup

1. Copy the environment template and fill in one broker section:

   ```bash
   cp .env.example .env
   ```

   **OANDA demo/practice:** edit `.env`, uncomment the OANDA block, and
   paste your personal access token and demo account ID:

   ```bash
   ALPHABRIEF_OANDA_TOKEN=your_oanda_token_here
   ALPHABRIEF_OANDA_ACCOUNT_ID=your_demo_account_id_here
   ```

   **Alpaca Paper:** alternatively, uncomment the Alpaca block and paste
   your paper key and secret:

   ```bash
   ALPHABRIEF_ALPACA_KEY=your_paper_key_here
   ALPHABRIEF_ALPACA_SECRET=your_paper_secret_here
   ```

   **Never commit `.env`.** The project `.gitignore` already excludes
   it. Never paste broker secrets into chat, screenshots, logs, or issues.

2. Confirm the live-trading lock stays closed:

   ```bash
   grep ALPHABRIEF_LIVE_TRADING_ENABLED .env
   # Expected: ALPHABRIEF_LIVE_TRADING_ENABLED=false
   ```

   If you accidentally set this to `true`, `alphabrief scheduler run`
   will exit `3` on startup and `RiskGate` will reject every order
   intent. Both are fail-closed.

3. Confirm the paper execution policy is unchanged:

   ```bash
   grep -E "mode:|automated_execution:|require_human_review:" \
        config/paper_execution_policy.yaml
   # Expected:
   #   mode: paper
   #   automated_execution: false
   #   require_human_review: true
   ```

4. (Optional) Tune the reconciliation interval in `.env`:

   ```bash
   ALPHABRIEF_SCHEDULER_RECONCILE_INTERVAL_SECONDS=60
   ```

   The default is 60 seconds. Shorter intervals make the snapshot log
   denser; longer intervals make recon events easier to read.

## 4. Pre-Flight Checklist

Run these five commands in order. Every one must be green before you
start the 30-day run.

### 4.1 Standard quality gates

```bash
.venv/bin/ruff check .
.venv/bin/mypy packages apps tests
.venv/bin/pytest --ignore=tests/test_alpaca_adapter.py \
                 --ignore=tests/test_broker_api_live.py -q
```

All three should print a clean summary. Pytest should pass 1199+ tests;
the 12 sandbox-blocked localhost mock-broker tests are documented and
unrelated to paper readiness.

### 4.2 Project acceptance verifier

```bash
.venv/bin/alphabrief acceptance verify --compact
```

Expected: `11/11 checks passed`. The new `paper.preflight` check
appears in the output.

### 4.3 Paper-broker pre-flight

```bash
.venv/bin/alphabrief acceptance preflight --paper
```

Expected: single check `paper.preflight` reported as `passed`, exit
code `0`. This is the operator's one-shot "am I ready?" command — it
verifies the runbook exists, the env-var names are wired up, and the
locked configs are still in place.

### 4.4 Broker connectivity (live read)

```bash
.venv/bin/alphabrief broker status
```

Expected: payload includes `latest_snapshot` and `open_freeze_count: 0`.
The factory picks `OandaPaperAdapter` when both
`ALPHABRIEF_OANDA_TOKEN` and `ALPHABRIEF_OANDA_ACCOUNT_ID` are set;
otherwise it picks `AlpacaPaperAdapter` when both Alpaca credentials are
set. With no broker credentials it falls back to `NullBrokerAdapter`.

If the response shows `null` for `latest_snapshot`, no snapshot has
been recorded yet — that is normal before the first scheduler cycle.
The important thing is `open_freeze_count: 0`.

### 4.5 Scheduler smoke test

Run for 30 seconds, then send SIGINT:

```bash
.venv/bin/alphabrief scheduler run --reconcile-interval 5
# Ctrl-C after 30 seconds.
# Expected exit code: 0 (normal SIGINT shutdown).
```

Then confirm a fresh heartbeat landed:

```bash
.venv/bin/alphabrief scheduler heartbeats
```

Expected: at least one row with a `last_run_at` from the last 60
seconds.

### 4.6 AI trading scheduler flags

The AI daily cycle is disabled unless explicitly enabled:

```bash
export ALPHABRIEF_AI_TRADING_ENABLED=true
```

This lets the scheduler run `ai_daily_cycle` and record committee
cycles. By default, approved AI orders still use the local paper broker
path.

To submit AI-approved, non-human-review orders to the configured
external paper broker, enable the second flag:

```bash
export ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED=true
```

External paper submission remains fail-closed:

1. `ALPHABRIEF_LIVE_TRADING_ENABLED=true` still blocks the AI cycle.
2. `RiskGate` must approve the `OrderIntent`.
3. Human-review decisions are not submitted.
4. The order quantity is estimated from paper account buying power and
   checked against `PaperExecutionPolicy.max_order_notional`.
5. The AI `intent_id` is used as the broker `client_order_id` for
   adapter idempotency.

## 5. Starting the 30-Day Run

The recommended invocation:

```bash
.venv/bin/alphabrief scheduler run --reconcile-interval 60
```

Run under a process supervisor (tmux / systemd / launchd) so SIGINT and
SIGTERM are delivered cleanly. The scheduler traps both signals and
exits `0` on normal shutdown.

Exit codes that mean trouble:

| Exit | Cause | What to do |
|---|---|---|
| `0` | Normal SIGINT/SIGTERM shutdown | Restart and continue. |
| `2` | Startup reconciliation raised a freeze | Read `alphabrief broker status`. Investigate before unfreezing. |
| `3` | `ALPHABRIEF_LIVE_TRADING_ENABLED` is truthy | Edit `.env`, set it to `false`, restart. |
| Other | Unhandled exception | Capture stderr, restart, file an issue. |

Logs go to `~/.alphabrief/data/` by default, overrideable via
`ALPHABRIEF_DATA_DIR`.

## 6. Daily Observation Checkpoint

Every weekday, run:

```bash
.venv/bin/alphabrief broker status
.venv/bin/alphabrief scheduler status
.venv/bin/alphabrief broker reconcile --scope eod
```

What to look at:

- **`broker status`** — `latest_snapshot.all_match` should be `true`.
  If it flips to `false`, a reconciliation mismatch is recorded but
  not auto-frozen at `eod` scope. Compare it against `startup` and
  `cycle` snapshots before unfreezing anything.
- **`scheduler status`** — `heartbeat_count` should be monotonically
  non-decreasing. `open_freeze_count` should be `0`. `alerts_total`
  should be stable (no new alerts beyond the start-of-run noise).
- **`broker reconcile --scope eod`** — records a snapshot without
  triggering a freeze. Useful as a "today's digest" entry.

## 7. Weekly Observation Checkpoint

Once per week, aggregate:

- Total recon snapshots taken vs. number of `all_match=false`.
- RiskGate reject rate from `GET /api/v1/risk/audit` or
  `alphabrief risk audit`.
- Freeze event log: `alphabrief broker freezes`. Every freeze
  should have a reason and a corresponding investigation note.
- Adapter health: still on `OandaPaperAdapter` or `AlpacaPaperAdapter`,
  not silently fell back to `NullBrokerAdapter`.

Decide:

- Continue the observation.
- Adjust `RiskLimitConfig` (e.g. raise exposure caps).
- Open an investigation ticket for a recurring alert.

## 8. What To Do If a Freeze Fires

1. List open freezes:

   ```bash
   .venv/bin/alphabrief broker freezes
   ```

2. Read the diff in the most recent snapshot:

   ```bash
   .venv/bin/alphabrief broker status
   # latest_snapshot.diff_json contains the per-side comparison.
   ```

3. Investigate. **Never unfreeze to make an alert go away.** Common
   causes:
   - A broker order was modified out-of-band.
   - The local id map drifted from the broker id map (e.g. after
     a botched restart).
   - Cash or position totals diverged because the broker filled a
     paper order that the local `PaperBroker` did not see.

4. Clear the freeze with an explicit reason:

   ```bash
   .venv/bin/alphabrief broker unfreeze <event_id> \
       --reason "investigated: confirmed broker-side manual cancel; \
                 id map updated by hand"
   ```

   The reason is part of the freeze event log and is auditable.

## 9. Hard Safety Reminders

These are non-negotiable and should not be relaxed during the
observation period.

- **No live trading.** The scheduler exits `3` on
  `ALPHABRIEF_LIVE_TRADING_ENABLED=true`. `RiskGate` rejects every
  intent in that mode. The Alpaca adapter refuses URLs containing
  `live`; the OANDA adapter refuses live/`api-fxtrade` URLs and defaults
  to `https://api-fxpractice.oanda.com`.
- **No secrets in code, logs, prompts, screenshots, fixtures, or
  documentation.** The verifier scans runtime imports for direct
  provider SDK use. The alert sink scrubs `api_key`, `secret`,
  `password`, `token`, and `authorization` from outgoing payloads.
- **No unfreeze without investigation.** Every freeze needs a
  reason that survives an audit.
- **No provider SDK calls outside broker adapters.** Any import of
  provider SDKs such as `alpaca`, `alpaca_trade_api`, `alpaca-py`, or an
  OANDA SDK into runtime business code is rejected by the acceptance
  verifier. The adapters use `urllib` directly.
- **The 30 days are a minimum.** A shorter observation is not
  meaningful; longer is acceptable.

## 10. End-of-Run Reporting

After 30 stable days, prepare the operator-side report in
`reports/paper_observation/` with:

- Daily `broker status` snapshots.
- Daily `broker reconcile --scope eod` outputs.
- Weekly aggregate summaries.
- Freeze event log with reasons.
- RiskGate reject distribution.
- A final "ready for live-trading design review" verdict, signed by
  the operator.

The `FINAL_ACCEPTANCE_REPORT.md` upgrade path will reference this
folder when the project moves from local-acceptance to
operator-acceptance.

## 11. Out of Scope

This runbook does **not** cover:

- Live trading (no live adapter exists; not in scope).
- Cloud deployment, auth, secret rotation, backup, monitoring, or
  disaster drills (production operations, separate plan).
- Backtest credibility hardening (CAGR, Sharpe, Sortino, turnover,
  walk-forward, overfit audit — Phase 24+).
- Migrating to a live broker (the adapter port is paper-only today;
  live trading needs a separate design review).
