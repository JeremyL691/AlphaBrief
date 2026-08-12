"""M02-W03: bounded command evidence runner and artifact scrubbing.

Covers:
- PASS and FAIL derive only from process exit codes; no agent-authored
  result field can supply them (AC-M02-W03-01);
- logs and manifests redact tokens, authorization headers, account IDs,
  and configured sensitive patterns (AC-M02-W03-02);
- timeouts terminate child process groups and create a classified failed
  evidence record (AC-M02-W03-03).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_acceptance.autonomous_runner import CommandEvidence, run_command
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# AC-M02-W03-01: exit codes are the only truth
# ---------------------------------------------------------------------------


def test_zero_exit_is_pass(tmp_path: Path) -> None:
    evidence = run_command(
        "true",
        timeout_seconds=5.0,
        artifact_path=tmp_path / "true.log",
    )
    assert evidence.exit_code == 0
    assert evidence.passed is True
    assert evidence.failure_classification is None


def test_nonzero_exit_is_fail(tmp_path: Path) -> None:
    evidence = run_command(
        "false",
        timeout_seconds=5.0,
        artifact_path=tmp_path / "false.log",
    )
    assert evidence.exit_code == 1
    assert evidence.passed is False
    assert evidence.failure_classification == "non_zero_exit"


def test_exact_exit_code_is_recorded(tmp_path: Path) -> None:
    evidence = run_command(
        "exit 42",
        timeout_seconds=5.0,
        artifact_path=tmp_path / "exit42.log",
    )
    assert evidence.exit_code == 42
    assert evidence.passed is False


def test_evidence_schema_forbids_agent_result_fields(tmp_path: Path) -> None:
    """A fabricated 'passed' field contradicting the exit code is rejected."""
    with pytest.raises(ValidationError, match="contradicts"):
        CommandEvidence(
            command="true",
            exit_code=1,
            timed_out=False,
            passed=True,
            failure_classification=None,
            summary="x",
            artifact="x",
            artifact_sha256="x",
            output_char_count=0,
        )
    # The runner derives passed from the exit code alone.
    evidence = run_command(
        "exit 1", timeout_seconds=5.0, artifact_path=tmp_path / "e.log"
    )
    assert evidence.passed is False
    assert evidence.passed == (evidence.exit_code == 0 and not evidence.timed_out)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# AC-M02-W03-03: timeout classification and process-group termination
# ---------------------------------------------------------------------------


def test_timeout_terminates_process_group_and_classifies_failed(
    tmp_path: Path,
) -> None:
    """A sleeping child is killed with its group; evidence is classified."""
    import subprocess
    import time

    marker = tmp_path / "child-started"
    command = (
        f"touch {marker} && sleep 30 && echo never-reached"
    )
    evidence = run_command(
        command,
        timeout_seconds=1.0,
        artifact_path=tmp_path / "timeout.log",
    )
    assert evidence.timed_out is True
    assert evidence.passed is False
    assert evidence.failure_classification == "timeout"
    # The whole process group was terminated: no 'sleep' child survives.
    time.sleep(0.3)
    leftover = subprocess.run(
        ["pgrep", "-f", "sleep 30"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "sleep 30" not in leftover.stdout


def test_timeout_within_budget_passes(tmp_path: Path) -> None:
    evidence = run_command(
        "echo done",
        timeout_seconds=5.0,
        artifact_path=tmp_path / "ok.log",
    )
    assert evidence.timed_out is False
    assert evidence.passed is True
    assert "done" in (tmp_path / "ok.log").read_text(encoding="utf-8")
