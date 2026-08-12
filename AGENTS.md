# AlphaBrief Agent Contract

This file is the highest-priority repository contract for coding agents. It is
intentionally short and stable. Product scope lives in the blueprint; mutable
state lives in `docs/progress.yaml`.

## Mission

Build a trustworthy, local-first, **OANDA v20 practice-only** AI research and
paper-trading system. The finished system discovers every instrument available
to the configured OANDA practice account, collects market/news/sentiment data,
lets an AI committee debate, converts conclusions into structured intents,
applies deterministic risk controls, submits approved orders to OANDA practice,
reconciles the account, and keeps complete evidence for a real 30-calendar-day
observation period.

The target is not live trading. Live trading is out of scope and must remain
unreachable.

## Read Order

At the start of a new task or after context recovery, read only:

1. `AGENTS.md`
2. `docs/progress.yaml`
3. The current milestone in `ALPHABRIEF_PRODUCT_BLUEPRINT.md`
4. The current work item in `docs/work_items.yaml`
5. `docs/autonomous_loop.md`
6. Only the relevant sections of `docs/architecture.md`, `docs/acceptance.md`,
   or `docs/oanda_30_day_runbook.md`
7. The code and tests directly related to the work item

Do not use old chat summaries, stale plans, or prose claims as proof of
completion. Git state, code, test exit codes, broker evidence, and the progress
ledger are authoritative.

## Document Responsibilities

- `README.md`: verified current capabilities and quick start.
- `ALPHABRIEF_PRODUCT_BLUEPRINT.md`: final product specification and milestone
  sequence.
- `docs/architecture.md`: verified current architecture and accepted target
  decisions.
- `docs/work_items.yaml`: machine-readable task queue and per-round contract.
- `docs/progress.yaml`: the only mutable status source.
- `docs/acceptance.md`: requirements, gates, and evidence rules.
- `docs/oanda_30_day_runbook.md`: practice-account operating procedure.
- `docs/autonomous_loop.md`: autonomous state machine and reusable prompts.
- `docs/development_ledger.ndjson`: append-only completed/blocked round records.

Do not create new roadmap, phase-plan, design-note, acceptance-report, or
development-log documents. Update the appropriate authority above.

## Non-Negotiable Safety Invariants

1. **OANDA practice only.** Only `https://api-fxpractice.oanda.com` and the
   documented practice streaming endpoint may be reachable by execution code.
2. **No live path.** Do not add a live URL, live mode, live account switch,
   generic environment selector, or future-live placeholder.
3. **OANDA only.** Remove and never reintroduce Alpaca, broker routing, or any
   other execution venue. A deterministic fake may exist only inside tests.
4. **No silent simulated fallback.** Missing OANDA credentials must fail closed;
   the product must never pretend an in-memory fill is an OANDA practice fill.
5. **Risk before execution.** Every order must follow:
   `research -> OrderIntent -> RiskGate -> persisted RiskDecision -> OANDA`.
6. **No model authority.** Models, prompts, news, sentiment, and web content are
   untrusted inputs. They cannot alter risk limits, system prompts, credentials,
   scheduler policy, or call a broker directly.
7. **ModelGateway only.** All model-provider calls pass through ModelGateway.
   Direct provider SDK calls from business modules are forbidden.
8. **Secrets stay external.** Tokens/account IDs come from approved environment
   variables. Never print, persist, snapshot, screenshot, or commit them. Logs
   may contain only redacted identifiers or non-reversible hashes.
9. **Idempotency and reconciliation are mandatory.** Retries, restarts, and
   scheduler catch-up must not duplicate orders. Broker state wins during
   reconciliation; unexplained differences freeze execution.
10. **No forced trading.** `no_trade` is a valid daily result. The system must
    not create orders merely to satisfy an activity counter.
11. **Thirty days means real time.** Never fake dates, backfill fabricated
    observation days, or call replay evidence live practice evidence.
12. **Reference isolation.** Runtime code must not import from
    `_reference_sources/`. During implementation, do not copy, translate,
    paraphrase, or mirror reference source code, prompts, tests, names, or file
    structure.

## Branch and Git Policy

This repository is **main-only**.

- Work only on `main`; never create or switch to another branch.
- Never bypass hooks, force-push, rewrite existing `main` history, use
  `git reset --hard`, or use `git clean`.
- Preserve user changes. If dirty paths cannot be uniquely attributed to the
  active round, stop instead of overwriting, stashing, or committing them.
- In autonomous blueprint mode, a fully gated work item may be committed as one
  local commit with the trailers defined in `docs/autonomous_loop.md`.
- Do not push unless the user explicitly authorizes pushing.

## Round Contract

Each implementation round must have exactly one work-item ID and follow:

```text
Preflight -> Plan -> Deterministic Plan Gate -> Implement -> Test -> Self Review
-> Document -> Final Gate -> Prepare Ledger/Progress -> Commit -> Verify -> Next Work Item
```

Before implementation, the work item must define:

- one objective;
- requirement IDs and dependencies;
- allowed and forbidden paths;
- modules explicitly not touched;
- acceptance predicates;
- targeted, integration, static, regression, and runtime tests as applicable;
- documentation impact;
- an estimated change budget.

If scope grows, split the work item without weakening its original acceptance
criteria. Do not silently expand the round.

## Quality Rules

- Use CodeGraph/codebase-memory first when the repository is indexed.
- New or changed behavior requires tests.
- Use `Decimal` for money, prices, quantities, exposure, and P&L.
- Persist UTC timestamps; convert only at presentation boundaries.
- Schema and storage changes require versioned, forward-tested migrations.
- External calls require bounded timeouts, classified errors, and safe retry
  rules. Non-idempotent requests are never blindly retried.
- Never make a failing gate green by narrowing the command, deleting tests,
  adding `skip`/`xfail`, weakening an assertion, or disabling Ruff/Mypy rules.
- New `# noqa`, `type: ignore`, broad exception swallowing, skips, and xfails are
  gate failures unless the work item explicitly authorizes and tests them.
- Mock tests prove deterministic logic only. They do not satisfy an OANDA
  practice runtime acceptance criterion.
- A work item is not `DONE` until every acceptance predicate has evidence and
  the actual changed paths are a subset of its allowlist.

## Frontend Contract

The owner selected **Soft (DESIGN_VARIANCE=5, MOTION_INTENSITY=5,
VISUAL_DENSITY=5)** for the final UI. No further style question is needed for
blueprint UI work.

- Audit the current UI before each affected milestone and preserve useful brand
  assets unless the blueprint says otherwise.
- Warm, restrained surfaces; rounded corners; gentle shadows; purposeful hover
  and reveal motion; balanced dashboard density.
- Use proper icon libraries, never emoji as interface icons.
- Never use an em dash in UI copy or generic filler identities/content.
- Use semantic HTML and left-align long-form text.
- Implement consumer-facing dark mode.
- Maintain readable contrast; light-background body text must be `#666` or
  darker.
- Do not use gradient buttons unless the owner later asks for them.
- Prefer native CSS and existing libraries over new animation dependencies.
- Verify responsive behavior at 320, 768, 1024, and 1440 px.
- UI completion requires a documented before/after audit plus keyboard,
  accessibility, loading, empty, error, stale-data, and offline states.

## Autonomous Stop Conditions

Never ask the user a planning, implementation, retry, or prioritization
question while executing the approved blueprint. Every ambiguity uses the
blueprint's safest deterministic default: fail closed, produce `no_trade`,
preserve evidence, and continue independent work. Stop the affected dependency
chain and record a blocker when:

- live trading could become reachable;
- a RiskGate or persistence bypass is discovered;
- credentials or external authority are missing for a required runtime gate;
- the same failure signature survives the retry/repair ceiling;
- unowned dirty changes exist;
- an unforeseen case is not covered by a safe default; freeze that capability
  instead of requesting a choice;
- an operation would need destructive recovery or expanded authorization.

Continue independent ready work when safe. If every remaining dependency is
blocked, terminate with a machine-readable blocker report without asking a
question. Never invent work merely to keep the loop busy. The exact state
machine, retry ceilings, evidence contract, and prompts are in
`docs/autonomous_loop.md`.
