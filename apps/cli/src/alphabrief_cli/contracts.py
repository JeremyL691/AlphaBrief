"""Machine-readable CLI contracts (M13-W04).

Script-safe CLI conventions shared by every read and control command:
stable compact JSON output, documented deterministic exit codes with
structured stderr, and a local/API parity path that never acquires the
writer lease (REQ-UI-001, REQ-UI-002, REQ-UI-010).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, cast

#: Documented deterministic exit codes (stable for scripts).
EXIT_SUCCESS = 0
EXIT_INTERNAL = 1
EXIT_VALIDATION = 2
EXIT_EMPTY = 3
EXIT_PARTIAL = 4
EXIT_CONFLICT = 5
EXIT_UNAVAILABLE = 6
EXIT_FROZEN = 7

#: Stable machine-readable names for each exit code.
EXIT_CODE_NAMES: dict[int, str] = {
    EXIT_SUCCESS: "success",
    EXIT_INTERNAL: "internal_error",
    EXIT_VALIDATION: "validation",
    EXIT_EMPTY: "empty",
    EXIT_PARTIAL: "partial",
    EXIT_CONFLICT: "conflict",
    EXIT_UNAVAILABLE: "unavailable",
    EXIT_FROZEN: "frozen",
}


class CliExit(Exception):
    """A deterministic CLI exit carrying a code and structured stderr."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def error_code(self) -> str:
        return EXIT_CODE_NAMES.get(self.code, "internal_error")


class EmptyResultError(CliExit):
    """A read returned no rows (documented exit code 3)."""

    def __init__(self, message: str) -> None:
        super().__init__(EXIT_EMPTY, message)


class PartialResultError(CliExit):
    """A read returned only part of the requested data (exit code 4)."""

    def __init__(self, message: str) -> None:
        super().__init__(EXIT_PARTIAL, message)


class ConflictError(CliExit):
    """The requested operation conflicts with current state (exit 5)."""

    def __init__(self, message: str) -> None:
        super().__init__(EXIT_CONFLICT, message)


class SourceUnavailableError(CliExit):
    """The backing source is unavailable (exit code 6)."""

    def __init__(self, message: str) -> None:
        super().__init__(EXIT_UNAVAILABLE, message)


class FrozenStateError(CliExit):
    """The target is frozen; the operation cannot proceed (exit 7)."""

    def __init__(self, message: str) -> None:
        super().__init__(EXIT_FROZEN, message)


def emit_json(payload: Any, *, pretty: bool = False) -> None:
    """Write stable compact JSON to stdout with no interactive prompts."""
    json.dump(
        payload,
        sys.stdout,
        indent=2 if pretty else None,
        sort_keys=True,
        separators=None if pretty else (",", ":"),
        default=str,
    )
    sys.stdout.write("\n")


def emit_error(exc: CliExit) -> None:
    """Write one structured stderr payload and exit deterministically."""
    json.dump(
        {
            "error_code": exc.error_code(),
            "exit_code": exc.code,
            "message": exc.message,
        },
        sys.stderr,
        sort_keys=True,
        separators=(",", ":"),
    )
    sys.stderr.write("\n")
    sys.exit(exc.code)


def normalize_payload(payload: Any) -> dict[str, Any]:
    """Canonical payload form shared by API-backed and local readers."""
    return cast(
        dict[str, Any],
        json.loads(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=str
            )
        ),
    )


def equivalent_normalized_payloads(
    api_payload: Any, local_payload: Any
) -> bool:
    """True when API-backed and local reads normalize identically."""
    return normalize_payload(api_payload) == normalize_payload(local_payload)


def read_local_or_api(
    *,
    api_path: str,
    local_reader: Callable[[], Any],
    api_reader: Callable[[str], Any],
) -> tuple[Any, str]:
    """Read through the API when it is up, otherwise locally.

    Returns ``(payload, source)`` where ``source`` is ``"api"`` or
    ``"local"``. The local path is read-only: it never acquires the
    scheduler writer lease, so it cannot create conflicting writer
    ownership with a running scheduler or API process.
    """
    try:
        payload = api_reader(api_path)
        return payload, "api"
    except Exception:
        return local_reader(), "local"
