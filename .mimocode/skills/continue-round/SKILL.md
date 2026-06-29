---
name: continue-round
description: "Continue implementing an AlphaBrief development round: read the plan, implement tasks, run quality gates (pytest/ruff/mypy), update docs, commit, and propose next tasks."
---

# Continue Development Round

You are continuing (or starting) the implementation of a development round for AlphaBrief.

## Trigger

The user says something like:
- "进行下一轮的开发" / "继续开发一轮此项目"
- "Continue developing Phase NN"
- "Continue Phase NN (<topic>)"
- A session continuation after plan approval

## Workflow

### Step 1: Locate the development plan

```bash
ls docs/development_plans/ | sort | tail -5
```

Read the latest (or specified) plan file. If the user specifies a phase number, read that specific plan.

### Step 2: Read project rules (if not already in context)

At minimum read:
```
AGENTS.md
ALPHABRIEF_DEVELOPMENT_CADENCE.md
```

### Step 3: Verify current state

```bash
git status
git log --oneline -5
.venv/bin/pytest --collect-only -q 2>/dev/null | tail -3
```

Confirm the starting test count and that there are no uncommitted changes that conflict.

### Step 4: Implement tasks

Follow the plan's implementation steps strictly:
- Only modify files listed in the plan
- Do not add unrequested features
- Do not touch modules listed as "NOT touched"
- Add tests for every new behavior
- Use `ponytail:` comments for intentional simplifications

### Step 5: Run quality gates

After implementation, run the full quality gate:

```bash
# Run relevant tests first
.venv/bin/pytest tests/test_relevant.py -q 2>&1 | tail -10

# Then full suite
.venv/bin/pytest -q 2>&1 | tail -3

# Lint
.venv/bin/ruff check . 2>&1 | tail -3

# Type check
.venv/bin/mypy packages apps tests 2>&1 | tail -3
```

Fix any failures before proceeding.

### Step 6: Update documentation

Update the relevant docs:
- `docs/roadmap.md` — mark phase complete, update status
- `docs/development_log.md` — add entry for this phase
- `docs/architecture.md` — if interfaces or module boundaries changed
- `docs/risk_model.md` — if risk logic changed

### Step 7: Commit

```bash
git add -A
git commit -m "phase-NN-<slug>: <brief description>"
```

Use the commit message format from the plan's completion criteria.

### Step 8: Post-implementation summary

Report to the user:
1. What was completed
2. Files modified/added
3. Test results (before → after count)
4. Any out-of-plan changes (should be none)
5. Any TODOs left
6. Next-round proposals (1-3 candidates)

## Key Constraints

- Stay within the approved plan
- If scope grows, stop and return to planning
- Never bypass RiskGate
- Never enable live trading
- Never copy from `_reference_sources/`
- Every risk-control change needs rejection + boundary tests

## Stopping Conditions

Return to Plan mode if:
- Task scope grows beyond the plan
- Architecture conflict discovered
- Many tests fail for unknown reasons
- A major new dependency is needed
- Risk-control boundaries become unclear

## Output

Completed implementation with all tests passing, documentation updated, and a commit. Summary presented to the user with next-round proposals.
