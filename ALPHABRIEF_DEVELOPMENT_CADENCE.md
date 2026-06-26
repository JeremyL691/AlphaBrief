# AlphaBrief Development Cadence

> This document defines AlphaBrief's long-term development cadence, the per-round Vibe Coding workflow, task-splitting principles, acceptance criteria, and review process.  
> It should sit alongside `ALPHABRIEF_PRODUCT_BLUEPRINT.md`, `AGENTS.md`, `docs/architecture.md`, `docs/risk_model.md`, `docs/rewrite_policy.md` as a required read-before-each-round guide.

---

## 1. Document Goal

AlphaBrief is a long-iteration, AI-native quantitative research and simulated-trading system. It should NOT be built with a "generate the whole project at once" approach.

This project follows a **small plan, small implementation, small test, small review** cadence.

Every round of development must:

1. Enter Plan mode first.
2. Read the project blueprint and engineering rules first.
3. Solve only one clearly-scoped problem per round.
4. Make no out-of-scope expansions.
5. Never copy reference source code.
6. Add tests for every new behavior.
7. Respect risk-control boundaries whenever trades, orders, positions, or model outputs are involved.
8. Summarize changes, test results, and next-round proposals at the end of every round.

---

## 2. Recommended Project Root Layout

Recommended structure:

```text
alphabrief/
├── ALPHABRIEF_PRODUCT_BLUEPRINT.md
├── ALPHABRIEF_DEVELOPMENT_CADENCE.md
├── AGENTS.md
├── README.md
├── docs/
│   ├── architecture.md
│   ├── roadmap.md
│   ├── risk_model.md
│   ├── agent_protocol.md
│   ├── model_gateway.md
│   ├── rewrite_policy.md
│   └── development_log.md
├── _reference_sources/
│   ├── QuantDinger/
│   ├── TradingGym/
│   └── TradingAgents/
├── apps/
├── packages/
├── strategies/
├── tests/
└── scripts/
```

Where:

- `ALPHABRIEF_PRODUCT_BLUEPRINT.md`: the highest-level product blueprint.
- `ALPHABRIEF_DEVELOPMENT_CADENCE.md`: this file, defining the development cadence.
- `AGENTS.md`: the engineering rules every Vibe Coding tool must follow each round.
- `docs/rewrite_policy.md`: constrains how reference source code may be used.
- `_reference_sources/`: used only for architectural reference. Do NOT import, copy, port, or rename-reuse any code from it.

---

## 3. Fixed Per-Round Development Flow

Every round must follow this flow:

```text
Plan
  ↓
Review Plan
  ↓
Implement
  ↓
Test
  ↓
Self Review
  ↓
Document
  ↓
Commit
  ↓
Next Task Proposal
```

### 3.1 Plan

At the start of each round, first put the Vibe Coding tool into Plan mode.

It must first read:

```text
ALPHABRIEF_PRODUCT_BLUEPRINT.md
ALPHABRIEF_DEVELOPMENT_CADENCE.md
AGENTS.md
docs/architecture.md
docs/roadmap.md
docs/risk_model.md
docs/rewrite_policy.md
current code structure
```

Then output:

1. This round's goal understanding.
2. Overview of currently relevant code.
3. Files to be added or modified.
4. Modules that will explicitly NOT be touched.
5. Implementation steps.
6. Test plan.
7. Risk points.
8. Completion criteria.

No code may be written until the plan is confirmed.

Important addition: add a folder to record each round's already-implemented plan as `.md` files, so that switching between different tools keeps everyone aware of what the previous round and earlier rounds did.

### 3.2 Review Plan

As the project owner, you must check whether the plan meets:

1. Is it only doing one small task?
2. Is it crossing into implementing future-stage features?
3. Could it bypass RiskGate?
4. Could it copy code from `_reference_sources/`?
5. Does it include tests?
6. Does it include documentation updates?
7. Can it be completed in a single development session?

If the plan is too large, it must be split into smaller pieces.

### 3.3 Implement

The implementation phase may only make the file changes listed in the plan.

Forbidden:

1. Drive-by refactoring of unrelated modules.
2. Drive-by adding unrequested features.
3. Drive-by wiring in real trading.
4. Drive-by adding complex dependencies.
5. Copying code from `_reference_sources/`.
6. Line-by-line translating reference-project files into AlphaBrief files.

Allowed:

1. Adding necessary types.
2. Adding interfaces.
3. Adding the minimum implementation.
4. Adding tests.
5. Updating relevant documentation.
6. Adding TODOs when necessary, but always with a stated reason.

### 3.4 Test

Each round must run the tests relevant to that round.

Recommended commands:

```bash
pytest
ruff check .
mypy packages apps
```

If the project is early and does not yet have a complete toolchain, you may start with:

```bash
pytest tests/<related_test_file>.py
```

At the end of each round, you must report:

```text
Which tests were run
Which tests passed
Which tests failed
Why they failed
Whether any risks are uncovered
```

### 3.5 Self Review

After implementation is complete, require the Vibe Coding tool to self-check:

1. Does it match this round's plan?
2. Did it modify any files outside the plan?
3. Did it add any unrequested features?
4. Are there security-boundary issues?
5. Are there risk-control bypass risks?
6. Are there reference-source-code similarity risks?
7. Are there future-maintenance hazards?
8. Does documentation need updating?

### 3.6 Document

Whenever a round touches architecture, interfaces, module boundaries, risk-control logic, or model-call logic, documentation MUST be updated.

Common documentation locations:

```text
docs/architecture.md
docs/risk_model.md
docs/agent_protocol.md
docs/model_gateway.md
docs/roadmap.md
docs/development_log.md
```

### 3.7 Commit

At the end of each round, a small commit is recommended.

Suggested commit message format:

```text
phase-1-core: add domain models
phase-1-data: add market data provider interface
phase-2-risk: add risk gate approval result
phase-3-models: add model provider interface
phase-3-agents: add AgentBrief schema
```

Do NOT mix multiple phases into one commit.

### 3.8 Next Task Proposal

At the end of each round, require the tool to propose 1 to 3 next-round candidates.

But the next round is still YOUR decision.

---

## 4. Standard Per-Round Prompt

To start each development round, you can use the template below:

```text
Please enter Plan mode.

This round's goal:
[Fill in a very small goal here]

Please read first:
- ALPHABRIEF_PRODUCT_BLUEPRINT.md
- ALPHABRIEF_DEVELOPMENT_CADENCE.md
- AGENTS.md
- docs/architecture.md
- docs/roadmap.md
- docs/risk_model.md
- docs/rewrite_policy.md
- current code structure

Important constraints:
- This round only does the specified goal
- Do not implement unrequested modules
- Do not copy any code from `_reference_sources/`
- Do not import from `_reference_sources/`
- Do not translate the reference project file by file
- Only extract behavior-level specifications
- Every new behavior must have a test
- If trade intent is involved, it must pass through RiskGate
- If model calls are involved, they must go through Model Gateway
- If orders, positions, accounts, fills, or portfolio state are involved, write audit logs or reserve audit interfaces
- Do not enable live trading by default

Please first output the plan, including:
1. This round's goal understanding
2. Currently relevant files
3. Files to add or modify
4. Modules that will NOT be touched
5. Implementation steps
6. Test plan
7. Risk points
8. Completion criteria

Do not write code until I confirm.
```

---

## 5. Post-Implementation Summary Prompt

After implementation is complete, use the template below to require the tool to review:

```text
Please summarize this round's development result.

Please output:
1. What was completed
2. Which files were modified
3. Which tests were added
4. Which commands were run
5. Test results
6. Are there any failing tests
7. Are there any unfinished TODOs
8. Were any out-of-plan files modified
9. Are there any risk-control, security, or reference-source similarity risks
10. Next-round proposals
```

---

## 6. Task-Splitting Principles

AlphaBrief tasks must be split small enough.

### 6.1 Examples of good tasks

```text
Implement core domain models: Bar, Signal, OrderIntent, RiskDecision
Implement MarketDataProvider interface
Implement CSV OHLCV loader
Implement Strategy interface
Implement a minimum version of the vectorized backtester
Implement backtest metrics: return, max drawdown, Sharpe
Implement RiskGate's max order value check
Implement PaperBroker's market-order simulated fill
Implement AgentBrief Pydantic schema
Implement ModelProvider interface
Implement OpenAI-compatible ProviderAdapter
Implement DailyBriefReport schema
```

### 6.2 Examples of bad tasks

```text
Build the complete AlphaBrief
Rewrite QuantDinger
Rewrite TradingGym
Rewrite TradingAgents
Build a complete AI auto-trading system
Implement all broker integrations
Implement the complete dashboard
Convert the reference project code into our project
Translate this file into our code style
```

The problems with bad tasks: scope is too large, boundaries are unclear, easy to copy, easy to introduce risk-control holes.

---

## 10. Branch and Commit Strategy

Recommended: use small branches.

```text
feat/core-domain-models
feat/csv-market-data-provider
feat/vectorized-backtester
feat/risk-gate-basic-limits
feat/paper-broker
feat/model-gateway-interface
feat/agent-brief-schema
```

Each branch only does one goal.

Pre-merge checks:

```text
Tests pass
Lint passes
Type check passes
Documentation updated
No out-of-plan file changes
No reference-source-copy risk
No RiskGate bypass
```

---

## 11. Reference-Source Usage Cadence

When you need to reference projects in `_reference_sources/`, you must use a clean-room cadence:

```text
Read Reference
  ↓
Write Behavior Spec
  ↓
Close Reference
  ↓
Implement AlphaBrief Version
  ↓
Write AlphaBrief Tests
  ↓
Similarity Review
```

Forbidden:

```text
Open reference files and let the tool rewrite directly
Translate function by function
Keep class/function names
Keep directory structure
Copy comments
Copy test cases
Copy config files
```

Allowed:

```text
Summarize what problem it solves
Summarize its user flows
Summarize its abstraction boundaries
Summarize its test scenarios
Re-implement using AlphaBrief's own models and naming
```

---

## 12. Risk-Control Development Cadence

Any task involving the following must be its own round:

```text
OrderIntent
Order
Fill
Position
PortfolioState
RiskGate
RiskLimit
PaperBroker
OrderRouter
AuditLog
BrokerAdapter
LiveTradingLock
```

Risk-control tasks MUST NOT be mixed with UI, model calls, or strategy generation in the same round.

Each risk-control task must at minimum include:

```text
Normal-pass tests
Rejection tests
Boundary-condition tests
Invalid-input tests
Audit-log tests or audit-interface reservations
```

---

## 13. Model-Integration Development Cadence

AlphaBrief is model-agnostic.

All model-vendor integrations must go through:

```text
Model Gateway
ModelProvider interface
ProviderAdapter
ModelRegistry
UsageTracker
```

Forbidden:

```text
Calling a vendor SDK directly inside an agent
Calling model APIs directly inside a strategy
Calling model APIs directly inside an execution module
Letting model output become an Order directly
Letting models bypass RiskGate
```

Suggested order for model-integration tasks:

```text
1. Define unified request/response schema
2. Define provider interface
3. Define registry
4. Implement one minimal adapter
5. Implement mock provider
6. Write tests
7. Then integrate the real provider
```

---

## 14. Dashboard Development Cadence

Dashboard must come LAST. Do NOT sink into the frontend from the start.

Recommended order:

```text
CLI works
API works
Data structures are stable
Report structures are stable
Then build dashboard
```

The first version of Dashboard only needs to display:

```text
Strategy list
Backtest reports
Equity curve
Paper portfolio
AgentBrief
Risk log
```

Do NOT start by building:

```text
Complex drag-and-drop strategy editor
Full permission system
Multi-user SaaS
Real-trading console
Strategy marketplace
Social features
```

---

## 15. Per-Round Acceptance Checklist

Before each round ends, you must check:

```text
[ ] Did it only complete this round's goal
[ ] Did it not implement unrelated features
[ ] Did it not copy reference source code
[ ] Did it not import from `_reference_sources/`
[ ] Did it add or update tests
[ ] Did it run the relevant tests
[ ] Did it update the necessary documentation
[ ] Did it not bypass RiskGate
[ ] Did it not enable live trading by default
[ ] Are all model calls going through Model Gateway
[ ] Is the commit message clear
[ ] Did it record next-round proposals
```

---

## 16. Stop Conditions

If any of the following occurs, you must stop implementation and return to Plan mode:

```text
Task scope grows
Need to change more modules than expected
Many tests fail for unknown reasons
Architecture conflict discovered
Risk-control boundaries are unclear
Reference-source similarity risk discovered
A major new dependency is needed
Requirements are unclear
```

Stopping is not failure; it prevents the project from going out of control.

---

## 17. Long-Term Project Principles

AlphaBrief's long-term development principles:

```text
Research first, trade later
Paper first, live later
Deterministic risk control first, AI decision-assist later
CLI first, dashboard later
Single-asset first, multi-asset later
Simple strategies first, complex strategies later
Mock provider first, real provider later
Testability first, intelligence later
Review first, optimize later
```

---

## 18. One-Sentence Principle

> Every round should make the system clearer, safer, and more testable — never more complex.