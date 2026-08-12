"""Secret and sensitive-content scrubbing for evidence artifacts (M02-W03).

Evidence logs and manifests must never carry secrets: bearer tokens,
``Authorization`` headers, API keys, full OANDA account IDs, and any
configured sensitive patterns are replaced with a fixed redaction marker
before an artifact is stored or hashed (REQ-OPS-002).
"""

from __future__ import annotations

import re

#: Fixed redaction marker.
REDACTED = "<redacted>"

#: Default sensitive patterns, applied case-insensitively:
#: Authorization headers, bearer tokens, common API-key env shapes, and
#: full OANDA v20 account IDs (e.g. ``101-004-1234567-001``).
DEFAULT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"authorization\s*:\s*[^\r\n]+", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]\s*[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"secret\s*[:=]\s*[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b\d{3}-\d{3}-\d{7,}-\d{3}\b"),
    re.compile(r"\b\d{9,}\b"),
)


def scrub_text(text: str, patterns: tuple[re.Pattern[str], ...] | None = None) -> str:
    """Replace every sensitive match in *text* with the redaction marker."""
    active = DEFAULT_PATTERNS if patterns is None else patterns
    scrubbed = text
    for pattern in active:
        scrubbed = pattern.sub(REDACTED, scrubbed)
    return scrubbed


def scrub_bytes(
    data: bytes, patterns: tuple[re.Pattern[str], ...] | None = None
) -> bytes:
    """Scrub binary output; undecodable bytes pass through unchanged."""
    try:
        return scrub_text(data.decode("utf-8"), patterns=patterns).encode("utf-8")
    except UnicodeDecodeError:
        return data


__all__ = [
    "DEFAULT_PATTERNS",
    "REDACTED",
    "scrub_bytes",
    "scrub_text",
]
