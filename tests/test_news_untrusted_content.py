"""M09-W05: untrusted external content sanitization.

- every external text fragment carries an untrusted-evidence marker,
  source identity, content hash, and bounded sanitized representation
  before model use (AC-M09-W05-01);
- sanitization logs contain no token, authorization header, complete
  account ID, prohibited full article, or executable external
  instruction (AC-M09-W05-03).
"""

from __future__ import annotations

import pytest
from alphabrief_news.untrusted import (
    DEFAULT_MAX_CHARS,
    SANITIZATION_VERSION,
    SanitizedEvidence,
    UntrustedContentError,
    build_sanitization_log,
    redact_secrets,
    sanitize_external_text,
)

# ---------------------------------------------------------------------------
# AC-M09-W05-01: marked, sourced, hashed, bounded sanitized evidence
# ---------------------------------------------------------------------------


def test_sanitized_evidence_carries_full_identity() -> None:
    evidence = sanitize_external_text(
        "The European Central Bank left rates unchanged.",
        source="fixture-news",
    )
    assert isinstance(evidence, SanitizedEvidence)
    assert evidence.untrusted is True
    assert evidence.source == "fixture-news"
    assert len(evidence.content_hash) == 64  # sha256 of the sanitized form
    assert evidence.sanitized_text == (
        "The European Central Bank left rates unchanged."
    )
    assert evidence.original_length == len(
        "The European Central Bank left rates unchanged."
    )
    assert evidence.neutralized_instructions == 0
    assert evidence.sanitization_version == SANITIZATION_VERSION


def test_sanitized_text_is_bounded() -> None:
    long_text = "word " * 10000
    evidence = sanitize_external_text(long_text, source="fixture-news")
    assert len(evidence.sanitized_text) <= DEFAULT_MAX_CHARS
    assert evidence.original_length == len(long_text)
    assert evidence.sanitized_text.endswith("...")


def test_paragraph_bound_applies() -> None:
    text = "\n\n".join(f"paragraph {i}" for i in range(50))
    evidence = sanitize_external_text(text, source="fixture-news")
    assert evidence.sanitized_text.count("\n\n") <= 9


def test_empty_text_fails_closed() -> None:
    with pytest.raises(UntrustedContentError) as excinfo:
        sanitize_external_text("   ", source="fixture-news")
    assert excinfo.value.kind == "empty_text"


def test_blank_source_fails_closed() -> None:
    with pytest.raises(UntrustedContentError) as excinfo:
        sanitize_external_text("text", source="  ")
    assert excinfo.value.kind == "invalid_source"


def test_sanitization_is_deterministic() -> None:
    first = sanitize_external_text("ECB holds rates.", source="fixture-news")
    second = sanitize_external_text("ECB holds rates.", source="fixture-news")
    assert first == second


# ---------------------------------------------------------------------------
# AC-M09-W05-03: scrubbed logs, no secrets or executable instructions
# ---------------------------------------------------------------------------


def test_sanitization_log_contains_no_content_or_secrets() -> None:
    evidence = sanitize_external_text(
        "Bearer abc12345 The ECB met. "
        "Authorization: Basic dXNlcjpwYXNz 101-004-1234567-001 "
        "api_key=super-secret",
        source="fixture-news",
    )
    log = build_sanitization_log(evidence)
    payload = log.model_dump(mode="json")
    rendered = str(payload)
    # Hashes and counts only: no token, header, account ID, or key.
    assert "abc12345" not in rendered
    assert "Basic" not in rendered
    assert "101-004-1234567-001" not in rendered
    assert "super-secret" not in rendered
    assert "Bearer" not in rendered
    assert log.content_hash == evidence.content_hash
    assert log.original_length == evidence.original_length
    assert log.sanitized_length == len(evidence.sanitized_text)


def test_secrets_redacted_from_sanitized_text() -> None:
    evidence = sanitize_external_text(
        "token=abc123 account 101-004-1234567-001 news",
        source="fixture-news",
    )
    assert "abc123" not in evidence.sanitized_text
    assert "101-004-1234567-001" not in evidence.sanitized_text
    assert "[REDACTED]" in evidence.sanitized_text


def test_redact_secrets_helpers() -> None:
    assert (
        redact_secrets("Bearer tok1234 done")
        == "[REDACTED] done"
    )
    assert redact_secrets("Authorization: xyz") == "[REDACTED]"
