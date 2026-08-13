"""Untrusted external content sanitization (M09-W05).

Every external text fragment is marked as untrusted evidence with its
source identity, content hash, and a bounded sanitized representation
before any model use (REQ-NEWS-006, AC-M09-W05-01). Prompt-injection
style instructions are neutralized deterministically — they can never
change system instructions, risk limits, execution settings, evidence
boundaries, or tool permissions (AC-M09-W05-02). Sanitization logs
contain no token, authorization header, complete account ID, prohibited
full article, or executable external instruction (AC-M09-W05-03,
REQ-AI-008, REQ-OPS-002).
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, ConfigDict, Field

#: The deterministic sanitization algorithm version.
SANITIZATION_VERSION = "2026-08-13.1"

#: Default bound for a sanitized external text fragment.
DEFAULT_MAX_CHARS = 1000

#: Default bound for the number of paragraphs retained.
DEFAULT_MAX_PARAGRAPHS = 10

#: Instruction-like patterns that are neutralized (never executed).
_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bignore\s+(?:(?:all|any|previous|the|above)\s+)*(?:instructions?|prompts?|messages?)",
        re.I,
    ),
    re.compile(
        r"\bdisregard\s+(?:(?:all|previous|the)\s+)*(?:instructions?|prompts?|messages?)",
        re.I,
    ),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(
        r"<\/?\|?(system|im_start|im_end|tool_call|tool_response)\|?>",
        re.I,
    ),
    re.compile(r"(new\s+)?system\s+instructions?\s*:", re.I),
    re.compile(r"override\s+(the\s+)?(risk|policy|limits?)", re.I),
    re.compile(
        r"\bignore\s+the\s+(risk\s+)?(gate|limits?|rules?)",
        re.I,
    ),
    re.compile(r"call\s+(the\s+)?(tool|function|broker)\s*\(", re.I),
)

#: Secret patterns redacted from sanitized text and logs.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.I),
    re.compile(r"Authorization\s*:\s*\S+", re.I),
    re.compile(r"\d{3}-\d{3}-\d{7,}-\d{3}"),
    re.compile(r"(api[_-]?key|token|secret)\s*[:=]\s*\S+", re.I),
)

_REDACTION = "[REDACTED]"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def neutralize_instructions(text: str) -> tuple[str, int]:
    """Neutralize instruction-like patterns; returns (text, removed_count).

    Neutralization replaces the instruction syntax with a marker — the
    instruction is never executed and never retained as an executable
    directive.
    """
    removed = 0
    for pattern in _INSTRUCTION_PATTERNS:
        text, count = pattern.subn("[NEUTRALIZED-EXTERNAL-INSTRUCTION]", text)
        removed += count
    return text, removed


def redact_secrets(text: str) -> str:
    """Redact tokens, authorization headers, and complete account IDs."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTION, text)
    return text


def bound_text(text: str, *, max_chars: int, max_paragraphs: int) -> str:
    """Bound a text fragment deterministically (chars and paragraphs)."""
    paragraphs = [
        paragraph.strip()
        for paragraph in text.split("\n\n")
        if paragraph.strip()
    ]
    paragraphs = paragraphs[:max_paragraphs]
    bounded = "\n\n".join(paragraphs)
    if len(bounded) > max_chars:
        bounded = bounded[: max_chars - 3].rstrip() + "..."
    return bounded


class SanitizedEvidence(BaseModel):
    """One bounded, marked, sanitized external text fragment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    untrusted: bool = True
    source: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    sanitized_text: str
    original_length: int = Field(ge=0)
    neutralized_instructions: int = Field(ge=0)
    sanitization_version: str = SANITIZATION_VERSION


class SanitizationLogRecord(BaseModel):
    """One scrubbed sanitization log record (never contains secrets)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    original_length: int = Field(ge=0)
    sanitized_length: int = Field(ge=0)
    neutralized_instructions: int = Field(ge=0)
    sanitization_version: str = SANITIZATION_VERSION


class UntrustedContentError(RuntimeError):
    """A classified fail-closed sanitization failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"untrusted content failed ({kind}): {detail}")


def sanitize_external_text(
    text: str,
    *,
    source: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_paragraphs: int = DEFAULT_MAX_PARAGRAPHS,
) -> SanitizedEvidence:
    """Sanitize one external text fragment for model use.

    The fragment is marked untrusted, bounded, and its instruction-like
    content is neutralized; secrets are redacted. The evidence carries
    the source identity and the content hash of the sanitized form.
    """
    if not text.strip():
        raise UntrustedContentError("empty_text", "external text is empty")
    if not source.strip():
        raise UntrustedContentError("invalid_source", "source must not be empty")

    neutralized, removed = neutralize_instructions(text)
    scrubbed = redact_secrets(neutralized)
    bounded = bound_text(
        scrubbed, max_chars=max_chars, max_paragraphs=max_paragraphs
    )
    return SanitizedEvidence(
        untrusted=True,
        source=source.strip(),
        content_hash=_content_hash(bounded),
        sanitized_text=bounded,
        original_length=len(text),
        neutralized_instructions=removed,
        sanitization_version=SANITIZATION_VERSION,
    )


def build_sanitization_log(
    evidence: SanitizedEvidence,
) -> SanitizationLogRecord:
    """One scrubbed log record: hashes and counts only, never content."""
    return SanitizationLogRecord(
        source=evidence.source,
        content_hash=evidence.content_hash,
        original_length=evidence.original_length,
        sanitized_length=len(evidence.sanitized_text),
        neutralized_instructions=evidence.neutralized_instructions,
        sanitization_version=evidence.sanitization_version,
    )


__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MAX_PARAGRAPHS",
    "SANITIZATION_VERSION",
    "SanitizationLogRecord",
    "SanitizedEvidence",
    "UntrustedContentError",
    "build_sanitization_log",
    "neutralize_instructions",
    "redact_secrets",
    "sanitize_external_text",
]
