"""M02-W06: loop-controller CLI wiring (AC-M02-W06-01 integration).

The CLI command delegates to the deterministic controller and emits the
outcome JSON; exit code 1 accompanies any non-DONE status. The pipeline
logic itself is covered by the meta-gate tests.
"""

from __future__ import annotations

import json

import pytest
from alphabrief_cli.acceptance_commands import acceptance_app
from typer.testing import CliRunner

runner = CliRunner()


def test_loop_command_emits_done_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_acceptance.loop_controller import RoundOutcome

    fake_outcome = RoundOutcome(
        work_item_id="M99-W01",
        status="DONE",
        next_work_item="M99-W02",
        commit_ref="abc1234",
        ledger_round_id="R-SYN-CLI",
    )

    def _fake_run(**kwargs: object) -> RoundOutcome:
        return fake_outcome

    monkeypatch.setattr(
        "alphabrief_acceptance.loop_controller.controller_run", _fake_run
    )

    result = runner.invoke(
        acceptance_app,
        [
            "loop",
            "M99-W01",
            "R-SYN-CLI",
            "M99-W01: cli wiring",
            "--artifacts-dir",
            "/tmp/artifacts",
            "--compact",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "DONE"
    assert payload["work_item_id"] == "M99-W01"
    assert payload["next_work_item"] == "M99-W02"


def test_loop_command_fails_with_non_done_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_acceptance.loop_controller import RoundOutcome

    fake_outcome = RoundOutcome(
        work_item_id="M99-W01",
        status="FAILED",
        detail="synthetic failure",
    )

    def _fake_run(**kwargs: object) -> RoundOutcome:
        return fake_outcome

    monkeypatch.setattr(
        "alphabrief_acceptance.loop_controller.controller_run", _fake_run
    )

    result = runner.invoke(
        acceptance_app,
        ["loop", "M99-W01", "R-SYN-FAIL", "M99-W01: cli fail", "--compact"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "FAILED"
