"""Atomic, owner-only credential storage.

Credentials live under ``<data_dir>/secrets/`` with mode ``0600`` and are
written atomically (write to a temporary file in the same directory, then
``os.replace``). Values are never logged, printed, or included in error
messages: :func:`redact` is the only supported way to surface one.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alphabrief_core import paths

#: File mode for credential files and their directory.
SECRET_FILE_MODE = 0o600

SECRET_DIR_MODE = 0o700


class SecretStoreError(RuntimeError):
    """Raised when a credential file cannot be read or written safely."""


def redact(value: str) -> str:
    """Return a short, non-reversible display form of a secret."""
    if not value:
        return "(empty)"
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}...{value[-2:]} (len={len(value)})"


def scrub_secrets(text: str) -> str:
    """Preserve evidence text while removing credential-shaped values."""
    patterns = (
        (r"Bearer\s+[A-Za-z0-9._~+/=-]+", "[REDACTED-TOKEN]"),
        (
            r"(?:api[_-]?key|secret|token|password|authorization)[\"']?"
            r"\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]+",
            "[REDACTED-SECRET]",
        ),
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED-SECRET]"),
        (r"\b[0-9a-f]{32}-[0-9a-f]{32}\b", "[REDACTED-TOKEN]"),
        (r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED-TOKEN]"),
        (r"\b\d{3}-\d{3}-\d{7,}-\d{3}\b", "[REDACTED-ACCOUNT-ID]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def scrub_payload(value: Any) -> Any:
    """Copy a JSON audit payload, scrubbing strings and credential fields."""
    if isinstance(value, str):
        return scrub_secrets(value)
    if isinstance(value, dict):
        return {
            scrub_secrets(str(key)): (
                "[REDACTED-SECRET]"
                if re.search(
                    r"(?:api[_-]?key|secret|token|password|authorization|account[_-]?id)",
                    str(key),
                    re.IGNORECASE,
                )
                else scrub_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_payload(item) for item in value]
    return value


def _secret_path(name: str) -> Path:
    if not name or "/" in name or name.startswith("."):
        raise SecretStoreError(f"invalid secret name: {name!r}")
    return paths.secrets_dir() / f"{name}.json"


def write_secret(name: str, payload: Mapping[str, Any]) -> Path:
    """Write ``payload`` as ``secrets/<name>.json`` with mode 0600."""
    directory = paths.secrets_dir()
    directory.chmod(SECRET_DIR_MODE)
    target = _secret_path(name)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=f".{name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(SECRET_FILE_MODE)
        os.replace(temp_path, target)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise SecretStoreError(f"could not write secret {name!r}: {exc}") from exc
    return target


def read_secret(name: str) -> dict[str, Any] | None:
    """Return the stored payload, or ``None`` when it does not exist."""
    target = _secret_path(name)
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SecretStoreError(f"could not read secret {name!r}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SecretStoreError(f"secret {name!r} is not a JSON object")
    return raw


def delete_secret(name: str) -> bool:
    """Remove a stored secret; returns ``True`` when a file was removed."""
    target = _secret_path(name)
    if not target.exists():
        return False
    try:
        target.unlink()
    except OSError as exc:
        raise SecretStoreError(f"could not delete secret {name!r}: {exc}") from exc
    return True


__all__ = [
    "SECRET_DIR_MODE",
    "SECRET_FILE_MODE",
    "SecretStoreError",
    "delete_secret",
    "read_secret",
    "redact",
    "write_secret",
]
