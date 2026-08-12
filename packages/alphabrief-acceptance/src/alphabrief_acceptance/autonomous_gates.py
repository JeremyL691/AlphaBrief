"""Scope, safety, and test-delta gates for the autonomous loop (M02-W04).

Every round's actual Git changes are checked against the resolved
execution contract:

- the scope gate rejects any changed path outside the resolved allowlist
  (and any path inside the resolved forbidden set);
- the safety gate rejects live hosts, other-broker production
  references, reference-source imports, and seeded secrets in changed
  content;
- the test-delta gate rejects deleted tests and new skip/xfail/noqa/
  type-ignore markers or weakened quality configuration unless the
  round explicitly authorizes them.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from alphabrief_acceptance.autonomous_schemas import ExecutionContractSchema

# ---------------------------------------------------------------------------
# Scope gate
# ---------------------------------------------------------------------------


def path_matches_glob(path: str, pattern: str) -> bool:
    """Return True when *path* matches a repository-relative glob.

    ``**`` matches across directory separators; a bare pattern without a
    slash also matches any file with that name anywhere in the tree.
    """
    normalized = path.replace("\\", "/")
    if fnmatch.fnmatch(normalized, pattern):
        return True
    if "/" not in pattern and fnmatch.fnmatch(Path(normalized).name, pattern):
        return True
    return False


def scope_gate_violations(
    *,
    contract: ExecutionContractSchema,
    changed_paths: Iterable[str],
) -> list[str]:
    """Return violations for changed paths outside the resolved allowlist.

    A path fails when it is not covered by the resolved allowlist or is
    covered by the resolved forbidden set.
    """
    allowed = contract.resolved_allowed_paths
    forbidden = contract.resolved_forbidden_paths
    violations: list[str] = []
    for changed in changed_paths:
        is_allowed = any(path_matches_glob(changed, pattern) for pattern in allowed)
        is_forbidden = any(
            path_matches_glob(changed, pattern) for pattern in forbidden
        )
        if is_forbidden:
            violations.append(
                f"{changed} is inside the resolved forbidden paths"
            )
        elif not is_allowed:
            violations.append(f"{changed} is outside the resolved allowlist")
    return violations


# ---------------------------------------------------------------------------
# Safety gate
# ---------------------------------------------------------------------------

#: Live trading hosts that must never appear in changed production content.
_LIVE_HOST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://api-fxtrade\.oanda\.com", re.IGNORECASE),
    re.compile(r"\blive_trading_enabled\s*[:=]\s*(1|true|yes|on)\b", re.IGNORECASE),
)

#: Other-broker or removed execution surfaces in changed production content.
_OTHER_BROKER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\balpaca", re.IGNORECASE),
    re.compile(r"broker\.routing|RoutingBrokerAdapter|SimulatedBrokerAdapter"),
)

#: Reference-source imports that must never appear in changed content.
_REFERENCE_IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(from|import)\s+_reference_sources\b", re.MULTILINE),
)

#: Seeded-secret patterns in changed content (tokens, keys, account IDs).
_SEEDED_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
    re.compile(
        r"(?:api[_-]?key|secret|token)\s*[:=]\s*[A-Za-z0-9._~+/=-]{12,}",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{3}-\d{3}-\d{7,}-\d{3}\b"),
)


def safety_gate_violations(
    *,
    changed_files: Mapping[str, str],
) -> list[str]:
    """Return safety violations found in changed file content.

    Live hosts, other-broker or removed execution surfaces, reference
    imports, and seeded secrets each fail the gate. ``changed_files``
    maps repository-relative paths to their new content.
    """
    violations: list[str] = []
    for path, content in changed_files.items():
        for pattern in _LIVE_HOST_PATTERNS:
            if pattern.search(content):
                violations.append(
                    f"{path} contains a live trading reference"
                )
        for pattern in _OTHER_BROKER_PATTERNS:
            if pattern.search(content):
                violations.append(
                    f"{path} contains another broker or removed execution surface"
                )
        for pattern in _REFERENCE_IMPORT_PATTERNS:
            if pattern.search(content):
                violations.append(
                    f"{path} imports from _reference_sources"
                )
        for pattern in _SEEDED_SECRET_PATTERNS:
            if pattern.search(content):
                violations.append(
                    f"{path} contains a seeded secret pattern"
                )
    return violations


# ---------------------------------------------------------------------------
# Test-delta gate
# ---------------------------------------------------------------------------

#: Test-delta markers that require explicit authorization.
_WEAKENING_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bskip\s*\("), "skip"),
    (re.compile(r"\bxfail\s*\("), "xfail"),
    (re.compile(r"#\s*noqa"), "noqa"),
    (re.compile(r"type:\s*ignore"), "type-ignore"),
)

#: Quality configuration files whose weakening is gated.
_QUALITY_CONFIG_PATHS = frozenset({"pyproject.toml", "ruff.toml", "mypy.ini"})


def _is_test_path(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py")


def delta_gate_violations(
    *,
    deleted_paths: Iterable[str],
    changed_files: Mapping[str, str],
    authorized_paths: Iterable[str] = (),
    authorized_markers: Iterable[str] = (),
) -> list[str]:
    """Return test-delta violations unless explicitly authorized.

    Deleted tests, newly added weakening markers in changed files, and
    quality-config changes all fail unless the round authorizes them.
    """
    authorized = frozenset(authorized_paths)
    markers_ok = frozenset(authorized_markers)
    violations: list[str] = []

    for deleted in deleted_paths:
        if _is_test_path(deleted) and deleted not in authorized:
            violations.append(
                f"{deleted} deletes a test without explicit authorization"
            )

    for path, content in changed_files.items():
        if path in authorized:
            continue
        if path in _QUALITY_CONFIG_PATHS:
            violations.append(
                f"{path} changes quality configuration without authorization"
            )
        if not _is_test_path(path):
            continue
        for pattern, marker in _WEAKENING_MARKERS:
            if marker in markers_ok:
                continue
            if pattern.search(content):
                violations.append(
                    f"{path} adds a {marker} marker without authorization"
                )
    return violations


__all__ = [
    "path_matches_glob",
    "safety_gate_violations",
    "scope_gate_violations",
    "delta_gate_violations",
]
