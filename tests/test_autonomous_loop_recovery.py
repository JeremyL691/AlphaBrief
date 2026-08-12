"""M02-W05: recovery verdicts for unfinished rounds.

Covers:
- a checkpoint whose base, dirty paths, and allowlist agree resumes only
  after re-running its last gate (AC-M02-W05-01);
- missing or ambiguous dirty-path ownership stops without reset,
  checkout, clean, stash, commit, or a user question (AC-M02-W05-02);
- repeated failure ceilings produce QUARANTINE and independent work
  remains selectable (AC-M02-W05-03).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_acceptance.autonomous_recovery import (
    classify_failure_ceiling,
    classify_recovery,
)
from alphabrief_acceptance.autonomous_schemas import (
    CheckpointSchema,
    ExecutionContractSchema,
    WorkQueueSchema,
    load_work_queue,
    resolve_execution_contract,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def queue() -> WorkQueueSchema:
    return load_work_queue(PROJECT_ROOT / "docs/work_items.yaml")


@pytest.fixture(scope="module")
def contract(queue: WorkQueueSchema) -> ExecutionContractSchema:
    return resolve_execution_contract(queue, "M02-W05")


def _checkpoint(**overrides: object) -> CheckpointSchema:
    """Build a valid checkpoint for recovery classification tests."""
    payload: dict[str, object] = {
        "schema_version": 1,
        "round_id": "R-20260813-M02-W05",
        "work_item_id": "M02-W05",
        "phase": "TESTING",
        "base_commit": "abc1234",
        "branch": "main",
        "attempt": 1,
        "last_verified_gate": "targeted-tests",
        "next_action": "fix the failing test",
        "changed_paths": [],
    }
    payload.update(overrides)
    return CheckpointSchema.model_validate(payload)


# ---------------------------------------------------------------------------
# AC-M02-W05-01: attributable checkpoint resumes after re-running its gate
# ---------------------------------------------------------------------------


def test_attributable_checkpoint_resumes_with_re_run_gate(
    contract: ExecutionContractSchema,
) -> None:
    verdict = classify_recovery(
        checkpoint=_checkpoint(),
        head_commit="abc1234",
        dirty_paths={"packages/alphabrief-acceptance/src/alphabrief_acceptance/autonomous_schemas.py"},
        contract=contract,
    )
    assert verdict.action == "RESUME"
    assert verdict.re_run_gate == "targeted-tests"


def test_checkpoint_base_mismatch_blocks(
    contract: ExecutionContractSchema,
) -> None:
    verdict = classify_recovery(
        checkpoint=_checkpoint(base_commit="old1234"),
        head_commit="abc1234",
        dirty_paths=set(),
        contract=contract,
    )
    assert verdict.action == "BLOCK"
    assert "does not match HEAD" in verdict.reason


# ---------------------------------------------------------------------------
# AC-M02-W05-02: ambiguous dirty paths stop safely
# ---------------------------------------------------------------------------


def test_dirty_paths_without_checkpoint_stop(
    contract: ExecutionContractSchema,
) -> None:
    verdict = classify_recovery(
        checkpoint=None,
        head_commit="abc1234",
        dirty_paths={"docs/progress.yaml"},
        contract=contract,
    )
    assert verdict.action == "STOP"
    assert "cannot be attributed" in verdict.reason


def test_dirty_paths_outside_allowlist_stop(
    contract: ExecutionContractSchema,
) -> None:
    verdict = classify_recovery(
        checkpoint=_checkpoint(),
        head_commit="abc1234",
        dirty_paths={"packages/alphabrief-execution/src/alphabrief_execution/broker/runtime.py"},
        contract=contract,
    )
    assert verdict.action == "STOP"
    assert "outside the allowlist" in verdict.reason


def test_checkpoint_without_gate_stops(
    contract: ExecutionContractSchema,
) -> None:
    verdict = classify_recovery(
        checkpoint=_checkpoint(last_verified_gate=None),
        head_commit="abc1234",
        dirty_paths=set(),
        contract=contract,
    )
    assert verdict.action == "STOP"
    assert "no gate to re-run" in verdict.reason


def test_clean_tree_without_checkpoint_selects_next(
    contract: ExecutionContractSchema,
) -> None:
    verdict = classify_recovery(
        checkpoint=None,
        head_commit="abc1234",
        dirty_paths=set(),
        contract=contract,
    )
    assert verdict.action == "SELECT_NEXT"


# ---------------------------------------------------------------------------
# AC-M02-W05-03: failure ceilings
# ---------------------------------------------------------------------------


def test_same_failure_ceiling_quarantines() -> None:
    verdict = classify_failure_ceiling(
        repair_cycles=2,
        same_failure_count=3,
        max_same_failure_repairs=3,
        max_total_repair_cycles=5,
    )
    assert verdict.action == "QUARANTINE"
    assert "same failure signature" in verdict.reason


def test_total_repair_ceiling_quarantines() -> None:
    verdict = classify_failure_ceiling(
        repair_cycles=5,
        same_failure_count=1,
        max_same_failure_repairs=3,
        max_total_repair_cycles=5,
    )
    assert verdict.action == "QUARANTINE"
    assert "total repair cycles" in verdict.reason


def test_repair_budget_remains_resumable() -> None:
    verdict = classify_failure_ceiling(
        repair_cycles=2,
        same_failure_count=2,
        max_same_failure_repairs=3,
        max_total_repair_cycles=5,
    )
    assert verdict.action == "RESUME"


def test_quarantined_item_keeps_independent_work_selectable(
    queue: WorkQueueSchema,
) -> None:
    """QUARANTINE only freezes the failing item; selection still works."""
    from alphabrief_acceptance.autonomous_schemas import load_progress
    from alphabrief_acceptance.autonomous_state_machine import (
        apply_transition,
        select_next_work_item,
    )

    progress = load_progress(PROJECT_ROOT / "docs/progress.yaml")
    with_state = progress.model_copy(
        update={
            "work_item_states": {
                **progress.work_item_states,
                "M02-W05": "TESTING",
            }
        }
    )
    mut = apply_transition(with_state, "M02-W05", "QUARANTINED")
    assert mut.work_item_states["M02-W05"] == "QUARANTINED"
    # Selection never picks the quarantined item and never errors.
    selected = select_next_work_item(queue, mut)
    assert selected != "M02-W05"
