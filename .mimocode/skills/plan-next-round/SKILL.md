---
name: plan-next-round
description: "Plan the next AlphaBrief development round: read project docs, assess current state, identify gaps, present direction options, and write a numbered development plan."
---

# Plan Next Development Round

You are planning the next development round for AlphaBrief, a local-first quant research + paper-trading workbench.

## Trigger

The user says something like:
- "制定下一轮开发计划" / "计划下一轮开发" / "制定下一轮的开发计划"
- "根据项目的验收标准，制定开发下一轮的计划"
- "Plan next development round"

## Workflow

### Step 1: Read project docs (parallel reads)

Read these files to understand the project's rules, architecture, and current state:

```
ALPHABRIEF_PRODUCT_BLUEPRINT.md
ALPHABRIEF_DEVELOPMENT_CADENCE.md
AGENTS.md
PROJECT_RULES.md
docs/architecture.md
docs/roadmap.md
docs/risk_model.md
docs/rewrite_policy.md
FINAL_ACCEPTANCE_REPORT.md
```

### Step 2: Assess current state

Run these commands to understand where the project stands:

```bash
git log --oneline -20          # recent commits
git status                     # uncommitted work
.venv/bin/pytest --collect-only -q 2>/dev/null | tail -5  # test count
ls docs/development_plans/     # existing plans
ls packages/ apps/             # module structure
```

### Step 3: Explore codebase for gaps

Use Agent subagents to do thorough exploration:
- One agent: explore overall architecture and roadmap
- One agent: explore recent phases (last 2-3 commits) to understand what was just finished
- One agent: find stubs, TODOs, gaps, and future work markers

### Step 4: Identify the next round's focus

Cross-reference:
1. What the roadmap says is next
2. What gaps/stubs exist in the code
3. What the FINAL_ACCEPTANCE_REPORT identifies as outstanding
4. What is feasible in a single session (small, scoped)

### Step 5: Present direction options to user

Ask the user to choose between 2-3 concrete options. Each option should:
- State what it achieves
- List the files/modules involved
- Estimate complexity (small / medium)
- Note any prerequisites

### Step 6: Write the development plan

After user chooses, write a numbered plan document to:
`docs/development_plans/NNNN-<short-name>.md`

Use the next sequential number (check `ls docs/development_plans/` for the latest).

Plan format (follow the project's existing convention):

```markdown
# NNNN Phase NN: <Title>

## Goal
<One paragraph: what this round achieves>

## Context
<What was just completed, what state the code is in>

## Changes
### Files to add
- `path/to/new_file.py` — purpose

### Files to modify
- `path/to/existing_file.py` — what changes

### Modules NOT touched
- `packages/some-module/` — out of scope

## Implementation Steps
1. Step one
2. Step two
...

## Test Plan
- What tests to add
- What tests to re-run
- Quality gate: pytest, ruff, mypy

## Completion Criteria
- [ ] All tests pass
- [ ] ruff clean
- [ ] mypy clean
- [ ] Documentation updated
- [ ] Commit with message: `phase-NN-<slug>`
```

### Step 7: Present plan for approval

Show the plan to the user. Do NOT start implementation until confirmed.

## Key Constraints

- Only ONE small goal per round
- No out-of-scope expansions
- No reference-source copying
- No live trading by default
- Every new behavior needs a test
- Risk-control tasks get their own round (not mixed with UI/model)

## Output

A numbered development plan file in `docs/development_plans/` and a summary presented to the user for confirmation.
