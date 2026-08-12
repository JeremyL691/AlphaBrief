"""Bounded command evidence runner for the autonomous loop (M02-W03).

Runs a declared command in its own process group, captures stdout and
stderr into one scrubbed artifact file, and derives PASS/FAIL strictly
from the process exit code. A timeout terminates the whole process group
and produces a classified failed evidence record; an agent-authored
result field can never supply PASS or FAIL (AC-M02-W03-01/03).
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from alphabrief_acceptance.autonomous_scrub import scrub_bytes

#: How long a killed child may take to exit before we force SIGKILL.
_GRACE_AFTER_TERM_SECONDS = 2.0

#: Marker used when the child produced no stdout/stderr.
_EMPTY_SUMMARY = "no output captured"


class CommandEvidence(BaseModel):
    """One command run with its derived evidence.

    ``passed`` is derived exclusively from the process exit code and the
    runner's own timeout classification; the model rejects any record
    whose ``passed`` field contradicts those values, so an agent-authored
    result field can never supply PASS or FAIL (AC-M02-W03-01).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: str
    exit_code: int
    timed_out: bool
    passed: bool
    failure_classification: str | None = None
    summary: str
    artifact: str
    artifact_sha256: str
    output_char_count: int

    @model_validator(mode="after")
    def passed_must_match_exit_code(self) -> CommandEvidence:
        derived = self.exit_code == 0 and not self.timed_out
        if self.passed != derived:
            raise ValueError(
                f"passed={self.passed} contradicts exit_code={self.exit_code} "
                f"timed_out={self.timed_out}"
            )
        return self


class CommandTimeoutError(RuntimeError):
    """Raised when a command exceeds its time budget."""


def _classify(exit_code: int, timed_out: bool) -> str | None:
    if timed_out:
        return "timeout"
    if exit_code != 0:
        return "non_zero_exit"
    return None


def run_command(
    command: str,
    *,
    timeout_seconds: float,
    artifact_path: Path | str,
    scrub_patterns: tuple[re.Pattern[str], ...] | None = None,
) -> CommandEvidence:
    """Run *command* bounded by *timeout_seconds* and record scrubbed evidence.

    The child runs in a new process group; on timeout the whole group is
    terminated so no descendant keeps running. The artifact file contains
    only scrubbed output and its SHA-256 is computed over the scrubbed
    bytes.
    """
    artifact = Path(artifact_path)
    artifact.parent.mkdir(parents=True, exist_ok=True)

    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    try:
        raw_output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_group(process)
        try:
            raw_output, _ = process.communicate(timeout=_GRACE_AFTER_TERM_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            raw_output, _ = process.communicate()

    exit_code = process.returncode
    scrubbed = scrub_bytes(raw_output or b"", patterns=scrub_patterns)
    artifact.write_bytes(scrubbed)
    artifact_sha256 = hashlib.sha256(scrubbed).hexdigest()
    output_char_count = len(scrubbed)

    summary = _EMPTY_SUMMARY if output_char_count == 0 else f"{output_char_count} chars"
    return CommandEvidence(
        command=command,
        exit_code=exit_code,
        timed_out=timed_out,
        passed=exit_code == 0 and not timed_out,
        failure_classification=_classify(exit_code, timed_out),
        summary=summary,
        artifact=str(artifact),
        artifact_sha256=f"sha256:{artifact_sha256}",
        output_char_count=output_char_count,
    )


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the child's whole process group, never just the leader."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


__all__ = [
    "CommandEvidence",
    "CommandTimeoutError",
    "run_command",
]
