# AlphaBrief Agent Instructions

This file is the coordination entry point for AI coding agents working on
AlphaBrief.

## Read First

Before planning or implementing a development round, read:

1. `ALPHABRIEF_PRODUCT_BLUEPRINT.md`
2. `ALPHABRIEF_DEVELOPMENT_CADENCE.md`
3. `PROJECT_RULES.md`
4. `docs/architecture.md`
5. `docs/roadmap.md`
6. `docs/risk_model.md`
7. `docs/rewrite_policy.md`
8. The current code structure relevant to the task

## Round Discipline

Each round must:

1. Define one small goal.
2. List files that may be changed.
3. List modules that will not be touched.
4. Include tests.
5. Include any required documentation update.
6. Avoid default live trading.
7. Avoid direct provider SDK calls outside ModelGateway.
8. Avoid any import from `_reference_sources/`.
9. Avoid copying or translating reference-source implementation details.

## Required Development Flow

Use the cadence defined in `ALPHABRIEF_DEVELOPMENT_CADENCE.md`:

```text
Plan -> Review Plan -> Implement -> Test -> Self Review -> Document -> Commit -> Next Task Proposal
```

Implementation must stay within the approved plan. If the task grows, return
to planning instead of expanding the implementation silently.

## Reference Source Handling

Reference projects are allowed only for behavior-level learning:

```text
Read Reference -> Write Behavior Spec -> Close Reference -> Implement AlphaBrief Version -> Test -> Similarity Review
```

Never copy code, prompts, comments, class names, function names, tests, or file
structure from reference projects.
