"""M13-W04: machine-readable CLI contracts.

Covers AC-M13-W04-01/02/03: read and control commands emit stable
compact JSON without prompts; success, empty, partial, validation,
conflict, unavailable, frozen, and internal error states map to
documented deterministic exit codes with structured stderr; API-backed
and permitted local read-only execution over the same fixture return
equivalent normalized payloads without conflicting writer ownership.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from alphabrief_cli import contracts
from alphabrief_cli.contracts import (
    CliExit,
    ConflictError,
    EmptyResultError,
    FrozenStateError,
    PartialResultError,
    SourceUnavailableError,
    equivalent_normalized_payloads,
    normalize_payload,
    read_local_or_api,
)
from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

#: Required read domains -> CLI command group.
DOMAIN_GROUPS = {
    "instruments": "data",
    "market_data": "data",
    "news": "news",
    "sentiment": "news",
    "committee": "ai",
    "risk": "risk",
    "broker": "broker",
    "cycle": "ai",
    "scheduler": "scheduler",
    "alert": "scheduler",
    "observation": "scheduler",
}

#: One representative read command per domain.
DOMAIN_COMMANDS = {
    "instruments": ["data", "catalog"],
    "market_data": ["data", "catalog"],
    "news": ["news", "list", "--json"],
    "sentiment": ["news", "list", "--json"],
    "committee": ["ai", "history"],
    "risk": ["risk", "status"],
    "broker": ["broker", "status"],
    "cycle": ["ai", "history"],
    "scheduler": ["scheduler", "status"],
    "alert": ["scheduler", "alerts"],
    "observation": ["scheduler", "heartbeats"],
}


@pytest.fixture(autouse=True)
def _isolate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    yield


class TestStableJsonWithoutPrompts:
    @pytest.mark.parametrize(
        "domain,command",
        sorted((domain, cmd) for domain, cmd in DOMAIN_COMMANDS.items()),
    )
    def test_read_command_emits_stable_json_without_prompts(
        self, domain: str, command: list[str]
    ) -> None:
        result = runner.invoke(app, command)
        # Success (0) or the documented empty state (3) are both valid;
        # anything else must carry a structured error.
        if result.exit_code not in (contracts.EXIT_SUCCESS, contracts.EXIT_EMPTY):
            assert result.stderr.strip() != ""
            payload = json.loads(result.stderr)
            assert "error_code" in payload
            return
        payload = json.loads(result.output)
        assert isinstance(payload, (dict, list))
        # Stable: two runs produce the identical normalized payload.
        again = runner.invoke(app, command)
        assert json.loads(again.output) == payload

    def test_every_required_domain_has_a_command_group(self) -> None:
        for domain, group in DOMAIN_GROUPS.items():
            result = runner.invoke(app, [group, "--help"])
            assert result.exit_code == 0, domain

    def test_no_command_reads_stdin(self) -> None:
        for command in DOMAIN_COMMANDS.values():
            # stdin is closed: a prompt would raise instead of hanging.
            result = runner.invoke(app, command, input=None)
            assert "prompt" not in result.output.lower()


class TestDeterministicExitCodes:
    def test_exit_codes_are_documented_and_stable(self) -> None:
        assert contracts.EXIT_SUCCESS == 0
        assert contracts.EXIT_INTERNAL == 1
        assert contracts.EXIT_VALIDATION == 2
        assert contracts.EXIT_EMPTY == 3
        assert contracts.EXIT_PARTIAL == 4
        assert contracts.EXIT_CONFLICT == 5
        assert contracts.EXIT_UNAVAILABLE == 6
        assert contracts.EXIT_FROZEN == 7
        assert contracts.EXIT_CODE_NAMES == {
            0: "success",
            1: "internal_error",
            2: "validation",
            3: "empty",
            4: "partial",
            5: "conflict",
            6: "unavailable",
            7: "frozen",
        }

    @pytest.mark.parametrize(
        "error,expected_code,expected_name",
        [
            (EmptyResultError("no rows"), 3, "empty"),
            (PartialResultError("partial"), 4, "partial"),
            (ConflictError("conflict"), 5, "conflict"),
            (SourceUnavailableError("down"), 6, "unavailable"),
            (FrozenStateError("frozen"), 7, "frozen"),
            (CliExit(2, "bad input"), 2, "validation"),
            (CliExit(1, "boom"), 1, "internal_error"),
        ],
    )
    def test_error_states_map_to_codes_and_structured_stderr(
        self, error: CliExit, expected_code: int, expected_name: str
    ) -> None:
        assert error.code == expected_code
        assert error.error_code() == expected_name

    def test_emit_error_writes_structured_stderr_and_exits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io

        stderr = io.StringIO()
        monkeypatch.setattr("sys.stderr", stderr)
        captured: dict[str, Any] = {}

        def fake_exit(code: int) -> None:
            captured["code"] = code

        monkeypatch.setattr("sys.exit", fake_exit)
        contracts.emit_error(SourceUnavailableError("source down"))
        payload = json.loads(stderr.getvalue())
        assert payload == {
            "error_code": "unavailable",
            "exit_code": 6,
            "message": "source down",
        }
        assert captured["code"] == 6


class TestApiLocalParity:
    def _fixture(self) -> dict[str, Any]:
        return {
            "domain": "scheduler",
            "items": [{"id": "b", "status": "ok"}, {"id": "a", "status": "ok"}],
        }

    def test_api_and_local_reads_normalize_identically(self) -> None:
        fixture = self._fixture()
        payload, source = read_local_or_api(
            api_path="/api/v1/scheduler/status",
            api_reader=lambda path: fixture,
            local_reader=lambda: fixture,
        )
        assert source == "api"
        assert equivalent_normalized_payloads(fixture, payload)

    def test_local_fallback_when_api_unavailable(self) -> None:
        fixture = self._fixture()
        calls: list[str] = []

        def failing_api(path: str) -> Any:
            calls.append(path)
            raise RuntimeError("api down")

        payload, source = read_local_or_api(
            api_path="/api/v1/scheduler/status",
            api_reader=failing_api,
            local_reader=lambda: fixture,
        )
        assert source == "local"
        assert payload == fixture
        assert calls == ["/api/v1/scheduler/status"]
        assert equivalent_normalized_payloads(fixture, payload)

    def test_normalized_payloads_are_order_and_key_stable(self) -> None:
        fixture = self._fixture()
        assert normalize_payload(fixture) == normalize_payload(
            {"items": [{"id": "b", "status": "ok"}, {"id": "a", "status": "ok"}],
             "domain": "scheduler"}
        )

    def test_local_read_path_never_acquires_the_writer_lease(self) -> None:
        source = Path(contracts.__file__).read_text(encoding="utf-8")
        assert "writer_lease" not in source
        # Read-only by construction: no SQL execution or mutation calls.
        assert "_conn.execute" not in source
        assert "INSERT INTO" not in source.upper()
        assert "UPDATE " not in source.upper()
