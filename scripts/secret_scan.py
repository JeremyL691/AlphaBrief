#!/usr/bin/env python3
"""Scan tracked files (and optionally the whole git history) for secrets.

Two modes:

``python scripts/secret_scan.py``
    Scan every file tracked by git for credential-shaped strings: OANDA
    account IDs, OANDA-style tokens, ``sk-`` API keys, and assignments to
    credential-named variables. When a local ``.env`` exists, the real
    values in it are loaded (never printed) and matched against every
    tracked file.

``python scripts/secret_scan.py --history``
    Additionally walk every blob in the git history. Used for the S11
    release gate.

Exits 0 when clean, 1 when a finding is reported. Findings print the
file, line and a redacted excerpt only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Values that are deliberately fake and appear in fixtures or docs.
#: Every entry is reviewed: they are shaped like a secret but carry no
#: credential for any account.
KNOWN_FIXTURES: frozenset[str] = frozenset(
    {
        "101-004-1234567-001",
        "001-002-3456789-001",
        "999-004-9999999-001",
        "999-999-9999999-001",
        "101-004-1234567-002",
        "test-account",
        "test-token",
        "test-token-12345",
        "sk-test-secret-key-value-1234567890",
        "sk-test",
        "sk-test-key",
        "sk-abc123",
        "REDACTED",
        "supersecret",
        "secret",
        "explicit-key",
        "adanos_test_key",
        "your_password",
        "dXNlcjpwYXNz",
        "221-004-7654321-009",
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "sup3r-s3cret-value",
        "hunter2hunter2",
    }
)

#: Regex patterns for credential-shaped strings.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("oanda_account_id", re.compile(r"\b\d{3}-\d{3}-\d{6,}-\d{3}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    (
        "oanda_token",
        re.compile(r"\b[0-9a-f]{32}-[0-9a-f]{32}\b"),
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|api[_-]?secret|access[_-]?token|"
            r"bearer[_-]?token|password|passwd)\b\s*[:=]\s*[\"']([^\"'\s]{12,})[\"']"
        ),
    ),
)

#: File suffixes worth scanning.
SCAN_SUFFIXES = frozenset(
    {
        ".py",
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".cfg",
        ".ini",
        ".sh",
        ".js",
        ".mjs",
        ".ts",
        ".html",
        ".css",
        ".txt",
        ".example",
        ".env",
    }
)

SKIP_PREFIXES = ("_reference_sources/", ".git/")


@dataclass(frozen=True)
class Finding:
    """One redacted finding."""

    location: str
    kind: str
    excerpt: str


def _redact(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def _iter_content_lines(text: str) -> Iterator[tuple[int, str]]:
    yield from enumerate(text.splitlines(), start=1)


def scan_text(text: str, *, location: str) -> list[Finding]:
    """Return findings for one text blob."""
    findings: list[Finding] = []
    for number, line in _iter_content_lines(text):
        for kind, pattern in PATTERNS:
            for match in pattern.finditer(line):
                candidate = match.group(1) if match.groups() else match.group(0)
                if candidate in KNOWN_FIXTURES:
                    continue
                if any(fixture in candidate for fixture in KNOWN_FIXTURES):
                    continue
                findings.append(
                    Finding(
                        location=f"{location}:{number}",
                        kind=kind,
                        excerpt=_redact(candidate),
                    )
                )
    return findings


def scan_real_credentials(
    text: str, *, location: str, secrets: Iterable[str]
) -> list[Finding]:
    """Return findings when a real (non-fixture) credential appears."""
    findings: list[Finding] = []
    for secret in secrets:
        if len(secret) < 8:
            continue
        if secret not in text:
            continue
        findings.append(
            Finding(
                location=location,
                kind="real_credential_leak",
                excerpt=_redact(secret),
            )
        )
    return findings


def tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files: list[Path] = []
    for name in output.splitlines():
        if not name or name.startswith(SKIP_PREFIXES):
            continue
        path = REPO_ROOT / name
        if path.is_file():
            files.append(path)
    return files


#: Variable-name fragments whose values are treated as real credentials.
#: Only these are matched against tracked files, so ordinary settings such
#: as a data directory or a policy path never produce a finding.
_CREDENTIAL_NAME_HINTS = ("token", "key", "secret", "password", "account_id")


def read_local_secrets() -> list[str]:
    """Return real credential values from a local ``.env`` (never printed)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return []
    values: list[str] = []
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().lower()
        if not any(hint in name for hint in _CREDENTIAL_NAME_HINTS):
            continue
        cleaned = value.strip().strip('"').strip("'")
        if len(cleaned) >= 8:
            values.append(cleaned)
    return values


def scan_tracked(secrets: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    secret_list = list(secrets)
    for path in tracked_files():
        if (
            path.suffix
            and path.suffix not in SCAN_SUFFIXES
            and path.name != ".env.example"
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        location = str(path.relative_to(REPO_ROOT))
        findings.extend(scan_text(text, location=location))
        if secret_list:
            findings.extend(
                scan_real_credentials(text, location=location, secrets=secret_list)
            )
    return findings


def _history_blobs() -> Iterator[tuple[str, str]]:
    """Yield ``(revision:path, text)`` for every text blob in history."""
    listing = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    seen: set[str] = set()
    for line in listing.splitlines():
        sha, _, name = line.partition(" ")
        if not name or sha in seen or name.startswith(SKIP_PREFIXES):
            continue
        seen.add(sha)
        blob = subprocess.run(
            ["git", "cat-file", "-p", sha],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if blob.returncode != 0:
            continue
        try:
            text = blob.stdout.decode("utf-8")
        except UnicodeDecodeError:
            continue
        yield f"history:{name}", text


def scan_history(secrets: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    secret_list = list(secrets)
    for location, text in _history_blobs():
        findings.extend(scan_text(text, location=location))
        if secret_list:
            findings.extend(
                scan_real_credentials(text, location=location, secrets=secret_list)
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        action="store_true",
        help="also scan every blob in the git history",
    )
    args = parser.parse_args(argv)

    secrets = read_local_secrets()
    findings = scan_tracked(secrets)
    if args.history:
        findings.extend(scan_history(secrets))

    if findings:
        print(f"secret scan FAILED: {len(findings)} finding(s)")
        for finding in findings:
            print(f"  {finding.location} [{finding.kind}] {finding.excerpt}")
        return 1

    scope = "tracked files and git history" if args.history else "tracked files"
    print(f"secret scan OK: no credential-shaped strings in {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
