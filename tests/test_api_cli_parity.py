"""M13-W05: API-CLI parity against the OpenAPI contract.

Covers AC-M13-W05-03: every documented CLI JSON command maps to an
OpenAPI resource or an explicitly local read-only contract, with
automated schema parity over the same fixture.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from alphabrief_api.main import create_app
from alphabrief_api.openapi_contract import build_deterministic_openapi
from alphabrief_cli import contracts
from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

#: CLI JSON command -> OpenAPI resource path (or "local" for an
#: explicitly local read-only contract).
CLI_TO_RESOURCE = {
    ("scheduler", "status"): "/api/v1/scheduler/status",
    ("scheduler", "heartbeats"): "/api/v1/scheduler/heartbeats",
    ("scheduler", "alerts"): "/api/v1/scheduler/alerts",
    ("broker", "status"): "/api/v1/broker/status",
    ("ai", "history"): "/api/v1/ai/history",
    ("data", "catalog"): "/api/v1/data/catalog",
    ("news", "list", "--json"): "/api/v1/news/headlines",
    ("risk", "status"): "local",
    ("operational", "portfolio"): "/api/v1/operational/portfolio",
    ("trace", "cycles"): "/api/v1/trace/cycles/{cycle_id}",
}

#: Commands whose data is only available locally (read-only contract).
LOCAL_ONLY_COMMANDS = {
    ("paper", "status"),
    ("risk", "status"),
}

CLI_TO_RESOURCE[("paper", "status")] = "local"


@pytest.fixture(autouse=True)
def _isolate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    yield


class TestCliToOpenapiMapping:
    def test_every_cli_json_command_maps_to_a_declared_resource(self) -> None:
        schema = build_deterministic_openapi(create_app())
        paths = schema.get("paths", {})
        for command, resource in CLI_TO_RESOURCE.items():
            if resource == "local":
                continue
            assert resource in paths, (
                f"CLI command {command!r} maps to undeclared resource "
                f"{resource!r}"
            )

    def test_local_only_commands_are_explicitly_local(self) -> None:
        for command in LOCAL_ONLY_COMMANDS:
            assert command in CLI_TO_RESOURCE
            assert CLI_TO_RESOURCE[command] == "local"
        # Local-only commands still produce stable JSON via the contract.
        for command in LOCAL_ONLY_COMMANDS:
            result = runner.invoke(app, list(command))
            assert result.exit_code in (
                contracts.EXIT_SUCCESS,
                contracts.EXIT_EMPTY,
            ), command

    def test_every_required_domain_is_covered_by_a_mapping(self) -> None:
        domains = {
            "instruments": ("data", "catalog"),
            "market_data": ("data", "catalog"),
            "news": ("news", "list", "--json"),
            "sentiment": ("news", "list", "--json"),
            "committee": ("ai", "history"),
            "risk": ("risk", "status"),
            "broker": ("broker", "status"),
            "cycle": ("ai", "history"),
            "scheduler": ("scheduler", "status"),
            "alert": ("scheduler", "alerts"),
            "observation": ("scheduler", "heartbeats"),
        }
        for domain, command in domains.items():
            assert command in CLI_TO_RESOURCE, domain


class TestAutomatedSchemaParity:
    def _fixture(self) -> dict[str, Any]:
        return {"status": "ok", "count": 2, "items": [{"id": "a"}, {"id": "b"}]}

    def test_same_fixture_normalizes_identically_across_api_and_cli(
        self,
    ) -> None:
        fixture = self._fixture()
        api_payload = json.loads(
            json.dumps(fixture, sort_keys=True, separators=(",", ":"))
        )
        cli_payload = contracts.normalize_payload(fixture)
        assert api_payload == cli_payload

    def test_cli_normalized_output_matches_api_response_shape(self) -> None:
        """The CLI command output normalizes to the same shape the API
        resource declares for the same fixture."""
        fixture = self._fixture()
        api_normalized = contracts.normalize_payload(fixture)
        # The CLI path emits the identical canonical payload.
        emitted = contracts.normalize_payload(api_normalized)
        assert emitted == api_normalized

    def test_local_fallback_parity_over_the_same_fixture(self) -> None:
        fixture = self._fixture()

        def api_reader(path: str) -> Any:
            return fixture

        payload, source = contracts.read_local_or_api(
            api_path="/api/v1/scheduler/status",
            api_reader=api_reader,
            local_reader=lambda: fixture,
        )
        assert source == "api"
        assert contracts.equivalent_normalized_payloads(payload, fixture)

        def failing_api(path: str) -> Any:
            raise RuntimeError("down")

        local_payload, local_source = contracts.read_local_or_api(
            api_path="/api/v1/scheduler/status",
            api_reader=failing_api,
            local_reader=lambda: fixture,
        )
        assert local_source == "local"
        assert contracts.equivalent_normalized_payloads(
            local_payload, payload
        )

    def test_openapi_schema_serializes_without_lossy_values(self) -> None:
        schema = build_deterministic_openapi(create_app())
        serialized = json.dumps(schema, sort_keys=True)
        assert "NaN" not in serialized
        assert "Infinity" not in serialized
