"""Strategy/policy version hashing from real configuration content.

PROJECT_GUIDE 5.7 requires every persisted RiskDecision to carry a policy
hash **derived from the configuration file contents** (and an input hash
derived from the real snapshot contents), so an auditor can prove which
reviewed boundary approved an order. A constant version string is not
enough: it would keep matching after the reviewed files changed.

The hash covers the exact bytes of the reviewed configuration files, in a
stable order, each entry prefixed with the file's path relative to the
project root::

    config/alphabrief.yaml:<sha256>
    config/paper_execution_policy.yaml:<sha256>

Any change to either file changes the hash; a missing file fails closed
rather than silently hashing a smaller set.
"""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path

#: The reviewed configuration files whose content defines the strategy
#: and risk boundary. Order is irrelevant (entries are sorted).
POLICY_CONFIG_FILES = (
    "config/paper_execution_policy.yaml",
    "config/alphabrief.yaml",
)


class PolicyVersionError(RuntimeError):
    """Raised when the policy version cannot be derived from real files."""


def project_root(start: Path | None = None) -> Path:
    """The first ancestor of ``start`` (or cwd) holding ``pyproject.toml``."""
    base = (start or Path.cwd()).resolve()
    for directory in (base, *base.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    raise PolicyVersionError(
        f"no pyproject.toml found at or above {base}: cannot locate the "
        "reviewed configuration files"
    )


def default_policy_files(*, root: Path | None = None) -> tuple[Path, ...]:
    """The absolute paths of the reviewed configuration files."""
    base = root or project_root()
    return tuple(base / name for name in POLICY_CONFIG_FILES)


def policy_version_hash(
    files: Iterable[Path] | None = None, *, root: Path | None = None
) -> str:
    """Hash the real content of the reviewed configuration files.

    Raises :class:`PolicyVersionError` when a file is missing or empty, so
    a decision is never persisted against a policy hash that does not
    correspond to an actual reviewed configuration.
    """
    resolved = tuple(files) if files is not None else default_policy_files(root=root)
    if not resolved:
        raise PolicyVersionError("no policy files configured")
    base = root
    entries: list[str] = []
    for path in sorted(resolved, key=lambda item: str(item)):
        if not path.is_file():
            raise PolicyVersionError(f"policy file is missing: {path}")
        content = path.read_bytes()
        if not content.strip():
            raise PolicyVersionError(f"policy file is empty: {path}")
        label = path.name
        if base is not None:
            try:
                label = str(path.relative_to(base))
            except ValueError:
                label = path.name
        entries.append(f"{label}:{sha256(content).hexdigest()}")
    return sha256("\n".join(entries).encode()).hexdigest()


def policy_version_label(
    files: Iterable[Path] | None = None, *, root: Path | None = None
) -> str:
    """A short human-readable label for the current policy version."""
    return f"policy:{policy_version_hash(files, root=root)[:12]}"


__all__ = [
    "POLICY_CONFIG_FILES",
    "PolicyVersionError",
    "default_policy_files",
    "policy_version_hash",
    "policy_version_label",
    "project_root",
]
