"""Unfinished-round recovery verdicts (M02-W05).

Recovery after a crash or context compaction never trusts prose: it
classifies the checkpoint, the Git head, and the dirty paths against the
resolved allowlist and returns a deterministic verdict. When ownership
of dirty paths is missing or ambiguous the verdict is a safe stop — the
module never resets, checks out, cleans, stashes, or commits anything,
and never asks the user a question (REQ-OPS-006).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from alphabrief_acceptance.autonomous_schemas import (
    CheckpointSchema,
    ExecutionContractSchema,
)

RecoveryAction = Literal[
    "RESUME",       # checkpoint + dirty paths attributable; re-run last gate
    "SELECT_NEXT",  # no checkpoint, clean tree
    "STOP",         # dirty paths cannot be uniquely attributed
    "QUARANTINE",   # repair ceilings reached
    "BLOCK",        # checkpoint present but base/dirty mismatch
]


@dataclass(frozen=True)
class RecoveryVerdict:
    """One deterministic recovery classification."""

    action: RecoveryAction
    reason: str
    re_run_gate: str | None = None


def classify_recovery(
    *,
    checkpoint: CheckpointSchema | None,
    head_commit: str,
    dirty_paths: set[str] | frozenset[str],
    contract: ExecutionContractSchema,
) -> RecoveryVerdict:
    """Classify the recovery path for a crashed or compacted round.

    - RESUME: checkpoint base equals HEAD, every dirty path is inside the
      resolved allowlist, and the checkpoint names the gate to re-run.
    - SELECT_NEXT: no checkpoint and no dirty paths (clean tree).
    - STOP: dirty paths exist but cannot be uniquely attributed (no
      checkpoint, or paths outside the allowlist, or base mismatch).
    - BLOCK: checkpoint exists but its base commit does not match HEAD.
    """
    if checkpoint is None:
        if not dirty_paths:
            return RecoveryVerdict(
                action="SELECT_NEXT",
                reason="no checkpoint and clean tree",
            )
        return RecoveryVerdict(
            action="STOP",
            reason="dirty paths without a checkpoint cannot be attributed",
        )

    if checkpoint.base_commit != head_commit:
        return RecoveryVerdict(
            action="BLOCK",
            reason=(
                f"checkpoint base {checkpoint.base_commit} does not match "
                f"HEAD {head_commit}"
            ),
        )

    if checkpoint.last_verified_gate is None:
        return RecoveryVerdict(
            action="STOP",
            reason="checkpoint names no gate to re-run",
        )

    allowed = set(contract.resolved_allowed_paths)
    unexpected = sorted(
        path for path in dirty_paths if not _path_allowed(path, allowed)
    )
    if unexpected:
        return RecoveryVerdict(
            action="STOP",
            reason=f"dirty paths outside the allowlist: {', '.join(unexpected)}",
        )

    return RecoveryVerdict(
        action="RESUME",
        reason=(
            f"checkpoint base matches HEAD and {len(dirty_paths)} dirty "
            "paths are attributable"
        ),
        re_run_gate=checkpoint.last_verified_gate,
    )


def classify_failure_ceiling(
    *,
    repair_cycles: int,
    same_failure_count: int,
    max_same_failure_repairs: int,
    max_total_repair_cycles: int,
) -> RecoveryVerdict:
    """Classify a round's repair state against the failure ceilings.

    The same failure signature surviving the same-failure ceiling or the
    total repair budget produces QUARANTINE; otherwise the round may
    continue repairing.
    """
    if same_failure_count >= max_same_failure_repairs:
        return RecoveryVerdict(
            action="QUARANTINE",
            reason=(
                f"same failure signature survived {same_failure_count} "
                "repairs (ceiling {max_same_failure_repairs})"
            ),
        )
    if repair_cycles >= max_total_repair_cycles:
        return RecoveryVerdict(
            action="QUARANTINE",
            reason=(
                f"total repair cycles {repair_cycles} reached the ceiling "
                f"{max_total_repair_cycles}"
            ),
        )
    return RecoveryVerdict(
        action="RESUME",
        reason="repair budget remains available",
    )


def _path_allowed(path: str, allowed: set[str]) -> bool:
    import fnmatch

    normalized = path.replace("\\", "/")
    for pattern in allowed:
        if fnmatch.fnmatch(normalized, pattern):
            return True
        if "/" not in pattern and fnmatch.fnmatch(
            normalized.rsplit("/", 1)[-1], pattern
        ):
            return True
    return False


__all__ = [
    "RecoveryVerdict",
    "classify_failure_ceiling",
    "classify_recovery",
]
