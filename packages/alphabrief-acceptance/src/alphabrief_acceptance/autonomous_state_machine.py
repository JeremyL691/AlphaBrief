"""Deterministic topology, selection, and transition enforcement (M02-W02).

Implements the autonomous protocol's state machine over the strict
schemas from :mod:`alphabrief_acceptance.autonomous_schemas`:

- every work-item state transition must appear in
  :data:`LEGAL_TRANSITIONS`, otherwise it is rejected without mutating
  the progress authority;
- next-work selection is stable by dependency, priority, and ID, and
  never selects an item whose dependencies are not satisfied;
- milestone and project transitions require their declared aggregate
  gates.
"""

from __future__ import annotations

from alphabrief_acceptance.autonomous_schemas import (
    ItemStatus,
    ProgressSchema,
    WorkQueueSchema,
)

#: All legal work-item state transitions (autonomous_loop.md section 4.1).
#: Blocking states are entered from executing states; only
#: BLOCKED_EXTERNAL may return to READY; QUARANTINED/FAILED/SUPERSEDED
#: are terminal.
LEGAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # forward path
        ("BACKLOG", "READY"),
        ("READY", "PLANNING"),
        ("PLANNING", "PLAN_GATE"),
        ("PLAN_GATE", "IMPLEMENTING"),
        ("IMPLEMENTING", "TESTING"),
        ("TESTING", "SELF_REVIEW"),
        ("SELF_REVIEW", "DOCUMENTING"),
        ("DOCUMENTING", "FINAL_GATE"),
        ("FINAL_GATE", "COMMITTING"),
        ("COMMITTING", "DONE"),
        # rollbacks
        ("TESTING", "IMPLEMENTING"),
        ("SELF_REVIEW", "IMPLEMENTING"),
        ("FINAL_GATE", "IMPLEMENTING"),
        # external-evidence flow
        ("FINAL_GATE", "CODE_COMPLETE"),
        ("CODE_COMPLETE", "RUNTIME_VALIDATING"),
        ("RUNTIME_VALIDATING", "FINAL_GATE"),
        ("RUNTIME_VALIDATING", "DONE"),
        ("BLOCKED_EXTERNAL", "READY"),
        # blocking entries
        ("READY", "BLOCKED_EXTERNAL"),
        ("PLANNING", "BLOCKED_EXTERNAL"),
        ("PLANNING", "BLOCKED_DECISION"),
        ("PLAN_GATE", "BLOCKED_EXTERNAL"),
        ("PLAN_GATE", "BLOCKED_SAFETY"),
        ("PLAN_GATE", "BLOCKED_DECISION"),
        ("IMPLEMENTING", "BLOCKED_EXTERNAL"),
        ("IMPLEMENTING", "BLOCKED_SAFETY"),
        ("IMPLEMENTING", "BLOCKED_DECISION"),
        ("TESTING", "BLOCKED_EXTERNAL"),
        ("TESTING", "BLOCKED_SAFETY"),
        ("TESTING", "BLOCKED_DECISION"),
        ("SELF_REVIEW", "BLOCKED_EXTERNAL"),
        ("SELF_REVIEW", "BLOCKED_SAFETY"),
        ("DOCUMENTING", "BLOCKED_SAFETY"),
        ("FINAL_GATE", "BLOCKED_EXTERNAL"),
        ("FINAL_GATE", "BLOCKED_SAFETY"),
        ("COMMITTING", "BLOCKED_SAFETY"),
        ("RUNTIME_VALIDATING", "BLOCKED_EXTERNAL"),
        ("RUNTIME_VALIDATING", "BLOCKED_SAFETY"),
        # repair ceilings
        ("IMPLEMENTING", "QUARANTINED"),
        ("TESTING", "QUARANTINED"),
        ("SELF_REVIEW", "QUARANTINED"),
        ("QUARANTINED", "FAILED"),
    }
)

#: States that satisfy a code dependency for engineering items.
_ENGINEERING_SATISFIED = frozenset({"DONE", "CODE_COMPLETE"})

#: Terminal states with no outgoing transitions.
_TERMINAL_STATES = frozenset({"QUARANTINED", "FAILED", "SUPERSEDED"})


class IllegalTransitionError(ValueError):
    """Raised when a work-item transition is not allowed by the protocol."""

    def __init__(self, item_id: str, current: str, requested: str) -> None:
        self.item_id = item_id
        self.current = current
        self.requested = requested
        super().__init__(
            f"illegal transition for {item_id}: {current} -> {requested}"
        )


class IllegalSelectionError(ValueError):
    """Raised when a selection request violates the protocol."""


def apply_transition(
    progress: ProgressSchema,
    item_id: str,
    new_state: ItemStatus,
) -> ProgressSchema:
    """Return a new progress with one item transitioned.

    The input progress is never mutated (the schema is frozen); an
    illegal transition raises :class:`IllegalTransitionError` and leaves
    the input untouched.
    """
    current = progress.work_item_states.get(item_id)
    if current is None:
        raise IllegalTransitionError(item_id, "<unknown>", new_state)
    if (current, new_state) not in LEGAL_TRANSITIONS:
        raise IllegalTransitionError(item_id, current, new_state)
    updated_states = {**progress.work_item_states, item_id: new_state}
    return progress.model_copy(update={"work_item_states": updated_states})


def _state_of(
    queue: WorkQueueSchema,
    progress: ProgressSchema,
    item_id: str,
) -> str:
    item = next(
        (candidate for candidate in queue.work_items if candidate.id == item_id),
        None,
    )
    if item is None:
        raise IllegalSelectionError(f"unknown work item {item_id}")
    return progress.work_item_states.get(item_id, item.initial_status)


def dependencies_satisfied(
    queue: WorkQueueSchema,
    progress: ProgressSchema,
    item_id: str,
) -> bool:
    """Return True when every declared dependency is satisfied.

    Engineering items accept DONE and CODE_COMPLETE dependencies; the
    observation gate (M15/M16/M17) additionally requires DONE, enforced
    by the milestone gate callers.
    """
    item = next(
        (candidate for candidate in queue.work_items if candidate.id == item_id),
        None,
    )
    if item is None:
        raise IllegalSelectionError(f"unknown work item {item_id}")
    for dependency in item.depends_on:
        if _state_of(queue, progress, dependency) not in _ENGINEERING_SATISFIED:
            return False
    return True


def select_next_work_item(
    queue: WorkQueueSchema,
    progress: ProgressSchema,
) -> str | None:
    """Return the deterministic next READY work item, or None.

    Selection follows section 5 of the autonomous loop contract: from the
    current ACTIVE milestone, items whose current state is READY, with
    all dependencies satisfied, ordered by priority then lexicographic
    ID. Blocked or unknown dependencies are never selected.
    """
    milestone_id = progress.current.milestone_id
    candidates: list[str] = []
    for item in queue.work_items:
        if item.milestone_id != milestone_id:
            continue
        if _state_of(queue, progress, item.id) != "READY":
            continue
        if not dependencies_satisfied(queue, progress, item.id):
            continue
        candidates.append(item.id)

    def _key(item_id: str) -> tuple[int, str]:
        item = next(
            candidate for candidate in queue.work_items if candidate.id == item_id
        )
        return (item.priority, item.id)

    candidates.sort(key=_key)
    return candidates[0] if candidates else None


def milestone_gate_passes(
    queue: WorkQueueSchema,
    progress: ProgressSchema,
    milestone_id: str,
) -> bool:
    """Return True when the milestone's declared gate is satisfied.

    A milestone gate passes when its gate work item is DONE (or
    CODE_COMPLETE for engineering milestones that legitimately carry
    external-evidence state) and every required item of the milestone is
    DONE or CODE_COMPLETE. M15/M16/M17 only accept DONE.
    """
    milestone = next(
        (candidate for candidate in queue.milestones if candidate.id == milestone_id),
        None,
    )
    if milestone is None:
        raise IllegalSelectionError(f"unknown milestone {milestone_id}")

    gate_state = _state_of(queue, progress, milestone.gate_work_item)
    gate_satisfied = gate_state == "DONE" or (
        gate_state == "CODE_COMPLETE" and milestone_id not in {"M15", "M16", "M17"}
    )
    if not gate_satisfied:
        return False

    for item in queue.work_items:
        if item.milestone_id != milestone_id:
            continue
        state = _state_of(queue, progress, item.id)
        if state == "DONE":
            continue
        if state == "CODE_COMPLETE" and milestone_id not in {"M15", "M16", "M17"}:
            continue
        if state in {"BLOCKED_SAFETY", "QUARANTINED", "FAILED"}:
            return False
        if state not in _ENGINEERING_SATISFIED and state != "CODE_COMPLETE":
            return False
    return True


def project_engineering_ready(
    queue: WorkQueueSchema,
    progress: ProgressSchema,
) -> bool:
    """Return True when every M01..M15 milestone is DONE.

    Enforced by ``queue.policy.engineering_ready_requires_all_m01_m15_done``;
    CODE_COMPLETE is never sufficient for engineering readiness.
    """
    if not queue.policy.engineering_ready_requires_all_m01_m15_done:
        return True
    for index in range(1, 16):
        milestone_id = f"M{index:02d}"
        if progress.milestones.get(milestone_id) != "DONE":
            return False
    return True


__all__ = [
    "IllegalSelectionError",
    "IllegalTransitionError",
    "LEGAL_TRANSITIONS",
    "apply_transition",
    "dependencies_satisfied",
    "milestone_gate_passes",
    "project_engineering_ready",
    "select_next_work_item",
]
