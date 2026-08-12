"""Deterministic loop controller pipeline (M02-W06).

Integrates the strict schemas, the state machine, the evidence runner,
the scope/safety/test-delta gates, the ledger, the Git commit with
trailers, and next-item selection into one deterministic pipeline for a
single work item.

PASS and FAIL derive exclusively from process exit codes captured by the
evidence runner; the acceptance predicates are frozen at round start and
re-verified before commit, so a synthetic passing item advances and a
synthetic failing or acceptance-mutating item can never mark itself
DONE (anti-self-certification).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from alphabrief_acceptance.autonomous_gates import (
    delta_gate_violations,
    safety_gate_violations,
    scope_gate_violations,
)
from alphabrief_acceptance.autonomous_runner import (
    CommandEvidence,
    run_command,
)
from alphabrief_acceptance.autonomous_schemas import (
    CommandRecordSchema,
    LedgerRecordSchema,
    ProgressSchema,
    WorkQueueSchema,
    load_progress,
    load_work_queue,
    resolve_execution_contract,
)
from alphabrief_acceptance.autonomous_state_machine import (
    apply_transition,
    milestone_gate_passes,
    select_next_work_item,
)

RoundStatus = Literal[
    "DONE",
    "FAILED",
    "BLOCKED_ACCEPTANCE_MUTATION",
    "BLOCKED_SCOPE",
    "BLOCKED_SAFETY",
    "ERROR",
]

#: Default per-command time budget (seconds).
_DEFAULT_TIMEOUT_SECONDS = 120.0

#: Command layers in declared execution order.
_LAYERS = ("targeted", "integration", "static", "regression", "runtime")


class RoundOutcome(BaseModel):
    """The deterministic result of one controller round."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_item_id: str
    status: RoundStatus
    evidence: tuple[CommandEvidence, ...] = ()
    gate_violations: tuple[str, ...] = ()
    next_work_item: str | None = None
    commit_ref: str | None = None
    ledger_round_id: str | None = None
    detail: str | None = None


def _yaml_dump(progress: ProgressSchema) -> str:
    """Serialize progress as plain YAML (JSON-safe values round-trip)."""
    import yaml

    return yaml.safe_dump(progress.model_dump(mode="json"), sort_keys=False)


def _acceptance_fingerprint(queue: WorkQueueSchema, item_id: str) -> str:
    """Freeze the item's acceptance predicates as a content hash."""
    item = next(candidate for candidate in queue.work_items if candidate.id == item_id)
    payload = [
        {
            "id": predicate.id,
            "predicate": predicate.predicate,
            "evidence_type": predicate.evidence_type,
        }
        for predicate in item.acceptance
    ]
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _git(repo_root: Path, *args: str) -> str:
    """Run one git command inside *repo_root* and return its raw stdout.

    The output is not stripped: porcelain lines start with a status
    column that a leading-space trim would destroy.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _porcelain_paths(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (changed_or_untracked, deleted) paths from git status.

    ``-uall`` lists every untracked file individually instead of
    collapsing new directories, so the scope gate sees real paths.
    """
    status = _git(repo_root, "status", "--porcelain", "-uall")
    changed: list[str] = []
    deleted: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        code = line[:2]
        path = line[3:]
        if code.startswith("D"):
            deleted.append(path)
        else:
            changed.append(path)
    return changed, deleted


def _commit_with_trailers(
    repo_root: Path,
    message: str,
    round_id: str,
    work_item_id: str,
    requirement_ids: str,
) -> str:
    """Stage everything and commit with the protocol trailers."""
    _git(repo_root, "add", "-A")
    body = (
        f"{message}\n\n"
        f"AlphaBrief-Round: {round_id}\n"
        f"AlphaBrief-Work-Item: {work_item_id}\n"
        f"AlphaBrief-Requirements: {requirement_ids}"
    )
    _git(repo_root, "commit", "-m", body)
    return _git(repo_root, "rev-parse", "HEAD").strip()


def _append_ledger(
    ledger_path: Path,
    record: LedgerRecordSchema,
) -> None:
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json() + "\n")


def _mark_item_done(
    queue: WorkQueueSchema,
    progress: ProgressSchema,
    item_id: str,
) -> ProgressSchema:
    """Advance the item to DONE and promote milestones per their gates."""
    updated = apply_transition(progress, item_id, "DONE")
    item = next(candidate for candidate in queue.work_items if candidate.id == item_id)
    milestone_id = item.milestone_id

    milestones = dict(updated.milestones)
    if milestone_gate_passes(queue, updated, milestone_id):
        milestones[milestone_id] = "DONE"
        for milestone in queue.milestones:
            if milestones.get(milestone.id) != "BACKLOG":
                continue
            if all(
                milestones.get(dependency) == "DONE"
                for dependency in milestone.depends_on
            ):
                milestones[milestone.id] = "ACTIVE"
                break

    active_milestone = next(
        (m.id for m in queue.milestones if milestones.get(m.id) == "ACTIVE"),
        milestone_id,
    )
    # Selection runs against the promoted milestone authority.
    current = updated.current.model_copy(update={"milestone_id": active_milestone})
    promoted = updated.model_copy(update={"milestones": milestones, "current": current})
    next_item = select_next_work_item(queue, promoted)
    return promoted.model_copy(
        update={
            "current": current.model_copy(
                update={
                    "work_item_id": next_item or current.work_item_id,
                    "phase": "READY" if next_item else current.phase,
                    "round_id": None,
                    "base_commit": None,
                    "attempt": 0,
                    "last_verified_gate": None,
                    "next_action": f"start {next_item}" if next_item else None,
                }
            ),
        }
    )


def _queue_from_git(repo_root: Path, commit: str) -> WorkQueueSchema:
    """Load the work queue as committed at *commit* (anti-self-certification)."""
    import yaml

    raw = _git(repo_root, "show", f"{commit}:docs/work_items.yaml")
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise ValueError("baseline work queue is not a YAML mapping")
    return WorkQueueSchema.model_validate(parsed)


def controller_run(
    *,
    repo_root: Path | str,
    work_item_id: str,
    round_id: str,
    commit_message: str,
    artifacts_dir: Path | str | None = None,
    base_commit: str | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    dry_run: bool = False,
) -> RoundOutcome:
    """Run one fully gated work item and return its deterministic outcome.

    Order: freeze acceptance -> run declared commands (exit-code truth)
    -> scope/safety/test-delta gates -> acceptance-mutation check ->
    ledger append + progress update -> Git commit with trailers ->
    next-item selection.
    """
    root = Path(repo_root)
    artifact_root = Path(artifacts_dir) if artifacts_dir else root / ".agent-artifacts"
    try:
        queue = load_work_queue(root / "docs/work_items.yaml")
        progress = load_progress(root / "docs/progress.yaml")
        contract = resolve_execution_contract(queue, work_item_id)
        base = base_commit or _git(root, "rev-parse", "HEAD").strip()
        baseline_queue = _queue_from_git(root, base)
    except Exception as exc:  # noqa: BLE001 — controller error classification
        return RoundOutcome(
            work_item_id=work_item_id,
            status="ERROR",
            detail=f"preflight failed: {exc}",
        )

    # Freeze the acceptance from the baseline commit so a round cannot
    # mutate its own predicates and then self-certify against them.
    frozen = _acceptance_fingerprint(baseline_queue, work_item_id)
    round_artifacts = artifact_root / round_id
    evidence: list[CommandEvidence] = []
    for layer in _LAYERS:
        commands = getattr(contract.work_item.test_commands, layer)
        for index, command in enumerate(commands, start=1):
            evidence.append(
                run_command(
                    command,
                    timeout_seconds=timeout_seconds,
                    artifact_path=round_artifacts / f"{layer}-{index:02d}.log",
                )
            )

    if not all(item.passed for item in evidence):
        return RoundOutcome(
            work_item_id=work_item_id,
            status="FAILED",
            evidence=tuple(evidence),
            detail="one or more declared commands failed",
        )

    # Gates over the actual round changes.
    try:
        changed, deleted = _porcelain_paths(root)
        changed_content = {
            path: (root / path).read_text(encoding="utf-8")
            for path in changed
            if (root / path).is_file()
        }
        gate_violations = scope_gate_violations(
            contract=contract, changed_paths=changed + deleted
        )
        gate_violations.extend(
            safety_gate_violations(changed_files=changed_content)
        )
        gate_violations.extend(
            delta_gate_violations(
                deleted_paths=deleted,
                changed_files=changed_content,
            )
        )
    except Exception as exc:  # noqa: BLE001 — controller error classification
        return RoundOutcome(
            work_item_id=work_item_id,
            status="ERROR",
            evidence=tuple(evidence),
            detail=f"gate evaluation failed: {exc}",
        )
    if gate_violations:
        return RoundOutcome(
            work_item_id=work_item_id,
            status="BLOCKED_SCOPE",
            evidence=tuple(evidence),
            gate_violations=tuple(gate_violations),
            detail="scope/safety/test-delta gates rejected the round changes",
        )

    # Anti-self-certification: acceptance must be unchanged.
    try:
        reloaded = load_work_queue(root / "docs/work_items.yaml")
        if _acceptance_fingerprint(reloaded, work_item_id) != frozen:
            return RoundOutcome(
                work_item_id=work_item_id,
                status="BLOCKED_ACCEPTANCE_MUTATION",
                evidence=tuple(evidence),
                detail="the item's acceptance predicates changed during the round",
            )
    except Exception as exc:  # noqa: BLE001 — controller error classification
        return RoundOutcome(
            work_item_id=work_item_id,
            status="ERROR",
            evidence=tuple(evidence),
            detail=f"acceptance re-verification failed: {exc}",
        )

    # Ledger append + progress update.
    try:
        record = LedgerRecordSchema(
            record_type="ROUND",
            schema_version=1,
            round_id=round_id,
            work_item_id=work_item_id,
            result="DONE",
            commit_ref=f"AlphaBrief-Round:{round_id}",
            controller_enforced=True,
            changed_path_count=len(changed) + len(deleted),
            acceptance={
                predicate.id: "PASS" for predicate in contract.work_item.acceptance
            },
            commands=tuple(
                CommandRecordSchema(
                    command=item.command,
                    exit_code=item.exit_code,
                    summary=item.summary,
                )
                for item in evidence
            ),
            next_work_item=select_next_work_item(queue, progress),
            completed_at=datetime.now(UTC).isoformat(),
        )
        _append_ledger(root / "docs/development_ledger.ndjson", record)
        updated_progress = _mark_item_done(queue, progress, work_item_id)
        (root / "docs/progress.yaml").write_text(
            _yaml_dump(updated_progress),
            encoding="utf-8",
        )
        next_item = updated_progress.current.work_item_id
    except Exception as exc:  # noqa: BLE001 — controller error classification
        return RoundOutcome(
            work_item_id=work_item_id,
            status="ERROR",
            evidence=tuple(evidence),
            detail=f"ledger/progress update failed: {exc}",
        )

    commit_ref: str | None = None
    if not dry_run:
        try:
            commit_ref = _commit_with_trailers(
                root,
                commit_message,
                round_id,
                work_item_id,
                ",".join(contract.work_item.requirement_ids),
            )
        except Exception as exc:  # noqa: BLE001 — controller error classification
            return RoundOutcome(
                work_item_id=work_item_id,
                status="ERROR",
                evidence=tuple(evidence),
                detail=f"commit failed: {exc}",
            )

    return RoundOutcome(
        work_item_id=work_item_id,
        status="DONE",
        evidence=tuple(evidence),
        next_work_item=next_item,
        commit_ref=commit_ref,
        ledger_round_id=round_id,
    )


__all__ = ["RoundOutcome", "controller_run"]
