"""M15-W06: network allowlist scan.

Covers AC-M15-W06-01 network-allowlist gate: runtime sources reach no
live host or other broker; only the OANDA practice hosts are allowed.
"""

from __future__ import annotations

from pathlib import Path

from alphabrief_core import (
    ALLOWED_NETWORK_HOSTS,
    scan_network_allowlist,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestAllowlist:
    def test_only_practice_hosts_are_allowed(self) -> None:
        assert ALLOWED_NETWORK_HOSTS == (
            "api-fxpractice.oanda.com",
            "stream-fxpractice.oanda.com",
        )

    def test_runtime_sources_reach_no_live_or_other_broker(self) -> None:
        findings = scan_network_allowlist([REPO_ROOT / "packages"])
        assert findings == ()

    def test_api_and_cli_reach_no_live_or_other_broker(self) -> None:
        findings = scan_network_allowlist([REPO_ROOT / "apps"])
        assert findings == ()

    def test_scan_is_deterministic(self) -> None:
        sources = [REPO_ROOT / "packages", REPO_ROOT / "apps"]
        assert scan_network_allowlist(sources) == scan_network_allowlist(
            sources
        )
