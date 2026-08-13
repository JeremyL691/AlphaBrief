"""Security gates before any observation window (M15-W06).

Dependency integrity, supply-chain policy, tracked secret scan,
artifact scrub scan, live and other-broker network scan,
reference-source boundary, and static security rules must pass without
waiver before a real observation window can start. Prompt-injection
fixtures cannot alter system instructions, risk limits, broker tools,
provider routing, execution state, or evidence citation requirements.
A non-production rehearsal completes the full runbook flows without
counting rehearsal time as real observation (REQ-OPS-002, REQ-OPS-008).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: The seven required security gates (AC-M15-W06-01).
SECURITY_GATES: tuple[str, ...] = (
    "dependency_integrity",
    "supply_chain_policy",
    "secret_scan",
    "artifact_scrub",
    "network_allowlist",
    "reference_boundary",
    "static_security_rules",
)

#: The only network hosts runtime code may reach (OANDA practice).
ALLOWED_NETWORK_HOSTS: tuple[str, ...] = (
    "api-fxpractice.oanda.com",
    "stream-fxpractice.oanda.com",
)

#: Pattern for full OANDA account ids (never allowed in artifacts).
_FULL_ACCOUNT_ID = re.compile(r"account-\d{12,}")


class SecurityGateResult(BaseModel):
    """One deterministic security gate result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate: str = Field(min_length=1)
    passed: bool
    detail: str = Field(min_length=1)


class SecurityGatesReport(BaseModel):
    """One complete security-gate report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    gates: tuple[SecurityGateResult, ...]


def run_security_gates(truth: dict[str, Any] | None = None) -> SecurityGatesReport:
    """Run the seven security gates deterministically.

    Missing truth fails the gate closed with an explicit detail.
    """
    truth = truth or {}
    gates = tuple(
        SecurityGateResult(
            gate=name,
            passed=bool(truth.get(name, False)),
            detail=(
                "gate passed" if truth.get(name, False) else "no truth supplied"
            ),
        )
        for name in SECURITY_GATES
    )
    return SecurityGatesReport(
        passed=all(gate.passed for gate in gates),
        gates=gates,
    )


def scan_files_for_secrets(paths: list[Path]) -> tuple[str, ...]:
    """Deterministic secret scan: report files containing full account
    id patterns (fixtures build secrets at runtime, so scans stay
    clean)."""
    findings: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _FULL_ACCOUNT_ID.search(text):
            findings.append(str(path))
    return tuple(sorted(findings))


def scan_network_allowlist(paths: list[Path]) -> tuple[str, ...]:
    """Deterministic network scan: report runtime sources referencing
    hosts outside the OANDA practice allowlist (live hosts and other
    brokers)."""
    findings: list[str] = []
    pattern = re.compile(r"https?://([a-z0-9.\-]+)", re.IGNORECASE)
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            host = match.group(1).lower()
            if host not in ALLOWED_NETWORK_HOSTS and not host.endswith(
                ("127.0.0.1", "localhost")
            ):
                findings.append(f"{path}:{host}")
    return tuple(sorted(findings))


__all__ = [
    "ALLOWED_NETWORK_HOSTS",
    "SECURITY_GATES",
    "SecurityGateResult",
    "SecurityGatesReport",
    "run_security_gates",
    "scan_files_for_secrets",
    "scan_network_allowlist",
]
