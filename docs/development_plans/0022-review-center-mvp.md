# Development Plan 0022: Review Center MVP

## Goal

Complete Phase 5 by adding a read-only Review Center boundary for daily use and
post-trade review.

## Changes

1. Add `alphabrief_review`.
2. Add `ReviewCenterSnapshot` and summaries for strategies, backtests, daily
   briefs, model calls, paper portfolio, audit log, risk dashboard, and review
   journal.
3. Add local JSON snapshot read/write helpers.
4. Add plain-text viewers for every Phase 5 surface.
5. Add daily and weekly review journal generation.
6. Add tests and documentation.

## Out of Scope

1. Full Web Dashboard or FastAPI implementation.
2. New model calls, backtests, orders, risk decisions, or portfolio mutation.
3. Database storage or external persistence.
4. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_review_center.py` passes.
2. Full project tests pass.
3. Ruff and mypy pass.
4. Completion audit proves every Phase 5 blueprint item and standard is met.
