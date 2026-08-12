"""M02-W03: evidence artifact scrubbing (AC-M02-W03-02).

Logs and manifests redact tokens, authorization headers, account IDs,
and configured sensitive patterns before they are stored or hashed.
"""

from __future__ import annotations

import re
from pathlib import Path

from alphabrief_acceptance.autonomous_runner import run_command
from alphabrief_acceptance.autonomous_scrub import (
    REDACTED,
    scrub_text,
)


def test_authorization_header_is_redacted(tmp_path: Path) -> None:
    command = 'echo "Authorization: Bearer super-secret-token-abc"'
    evidence = run_command(
        command,
        timeout_seconds=5.0,
        artifact_path=tmp_path / "auth.log",
    )
    artifact = (tmp_path / "auth.log").read_text(encoding="utf-8")
    assert "super-secret-token-abc" not in artifact
    assert REDACTED in artifact
    assert "super-secret-token-abc" not in evidence.artifact_sha256


def test_full_oanda_account_id_is_redacted(tmp_path: Path) -> None:
    command = 'echo "account 101-004-1234567-001 ready"'
    run_command(
        command,
        timeout_seconds=5.0,
        artifact_path=tmp_path / "account.log",
    )
    artifact = (tmp_path / "account.log").read_text(encoding="utf-8")
    assert "101-004-1234567-001" not in artifact
    assert REDACTED in artifact


def test_configured_sensitive_pattern_is_redacted(tmp_path: Path) -> None:
    custom = (
        re.compile(r"MY_CUSTOM_SECRET[=:]\s*[A-Za-z0-9]+"),
    )
    command = 'echo "MY_CUSTOM_SECRET=topsecretvalue"'
    run_command(
        command,
        timeout_seconds=5.0,
        artifact_path=tmp_path / "custom.log",
        scrub_patterns=custom,
    )
    artifact = (tmp_path / "custom.log").read_text(encoding="utf-8")
    assert "topsecretvalue" not in artifact
    assert REDACTED in artifact


def test_scrub_text_redacts_bearer_and_api_key() -> None:
    scrubbed = scrub_text(
        "token=abc123 Authorization: Bearer xyz secret: s3cret api_key: k1"
    )
    assert "abc123" not in scrubbed
    assert "xyz" not in scrubbed
    assert "s3cret" not in scrubbed
    assert "k1" not in scrubbed
    # The greedy Authorization match consumes several tokens at once, so
    # at least two redaction markers are present.
    assert scrubbed.count(REDACTED) >= 2


