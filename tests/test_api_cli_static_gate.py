"""M13-W06: static operator-contract gate.

Covers AC-M13-W06-02: static scans find no arbitrary broker proxy,
route-local production state, offline-success placeholder, live
control, undocumented mutation, or sensitive OpenAPI example across
the API and CLI surfaces.
"""

from __future__ import annotations

import re
from pathlib import Path

from alphabrief_api.main import create_app
from alphabrief_api.openapi_contract import (
    build_deterministic_openapi,
    scan_for_sensitive_values,
)

API_ROUTES = Path(__file__).resolve().parents[1] / "apps/api/src/alphabrief_api"
CLI_SOURCES = Path(__file__).resolve().parents[1] / "apps/cli/src/alphabrief_cli"


def _python_sources(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


class TestNoArbitraryBrokerProxy:
    def test_route_modules_contain_no_generic_proxy(self) -> None:
        for source in _python_sources(API_ROUTES / "routes"):
            text = source.read_text(encoding="utf-8")
            for token in ("@router.api_route", "requests.request", "httpx.Client"):
                assert token not in text, f"{source.name} contains {token!r}"

    def test_write_gate_has_no_provider_references(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "packages/alphabrief-core/src/alphabrief_core/write_contracts.py"
        )
        text = source.read_text(encoding="utf-8")
        for token in ("import requests", "import urllib", "http.client", "oanda"):
            assert token not in text


class TestNoRouteLocalProductionState:
    def test_new_route_modules_have_no_module_level_mutable_state(self) -> None:
        for name in ("operational.py", "trace.py"):
            source = API_ROUTES / "routes" / name
            text = source.read_text(encoding="utf-8")
            # No singleton caches or accumulators at module scope.
            assert "_store:" not in text
            assert "_cache" not in text
            module_level = re.findall(
                r"^[a-z_][a-z0-9_]*(\s*:\s*[A-Za-z_][A-Za-z0-9_\[\], |]*)?"
                r"\s*=\s*(None|\{\}|\[\])\s*$",
                text,
                re.MULTILINE,
            )
            assert module_level == [], f"{name} has module-level state"

    def test_operational_and_trace_open_stores_per_request(self) -> None:
        for name in ("operational.py", "trace.py"):
            text = (API_ROUTES / "routes" / name).read_text(encoding="utf-8")
            assert "def _open_" in text
            assert "finally:" in text  # stores are always closed


class TestNoOfflineSuccessPlaceholder:
    def test_new_route_modules_never_hardcode_success(self) -> None:
        for name in ("operational.py", "trace.py"):
            text = (API_ROUTES / "routes" / name).read_text(encoding="utf-8")
            assert '"success": true' not in text
            assert '"success": True' not in text

    def test_missing_data_is_explicit_null_or_404(self) -> None:
        operational = (API_ROUTES / "routes" / "operational.py").read_text(
            encoding="utf-8"
        )
        assert "explicit" in operational  # documented fail-closed behavior
        trace = (API_ROUTES / "routes" / "trace.py").read_text(encoding="utf-8")
        assert "404" in trace


class TestNoLiveControl:
    def test_api_and_cli_sources_never_reference_the_live_host(self) -> None:
        pattern = re.compile(r"api-?fxtrade")
        for root in (API_ROUTES, CLI_SOURCES):
            for source in _python_sources(root):
                text = source.read_text(encoding="utf-8")
                assert pattern.search(text) is None, (
                    f"{source} references the live host"
                )

    def test_cli_never_exposes_a_live_mode_switch(self) -> None:
        for source in _python_sources(CLI_SOURCES):
            text = source.read_text(encoding="utf-8")
            assert "live_mode" not in text
            assert "--live" not in text


class TestNoUndocumentedMutation:
    def test_every_mutation_route_is_classified(self) -> None:
        known_operator = {"freeze", "unfreeze"}
        known_non_operator = {
            "",
            "check",
            "compare",
            "debate",
            "evaluate",
            "fetch",
            "generate",
            "kronos",
            "load",
            "orders",
            "reconcile",
            "releases",
            "route",
            "run",
            "signals",
            "specs",
        }
        for source in _python_sources(API_ROUTES / "routes"):
            text = source.read_text(encoding="utf-8")
            for match in re.finditer(
                r'@router\.(?:post|put|delete|patch)\(\s*"([^"]*)"', text
            ):
                operation = match.group(1).strip("/").split("/")[0] or ""
                assert operation in known_operator or operation in known_non_operator, (
                    f"{source.name} has undocumented mutation {operation!r}"
                )


class TestNoSensitiveOpenapiExamples:
    def test_generated_openapi_has_no_sensitive_values(self) -> None:
        schema = build_deterministic_openapi(create_app())
        assert scan_for_sensitive_values(schema) == []
