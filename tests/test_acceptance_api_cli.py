import json
from pathlib import Path

from alphabrief_api.main import app
from alphabrief_cli.main import app as cli_app
from fastapi.testclient import TestClient
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_api_returns_report() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/v1/acceptance/verify",
        params={"project_root": str(ROOT)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is True
    assert body["failed_count"] == 0


def test_acceptance_cli_returns_report() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli_app,
        [
            "acceptance",
            "verify",
            "--project-root",
            str(ROOT),
            "--compact",
        ],
    )

    assert result.exit_code == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["passed"] is True
    assert body["failed_count"] == 0


def test_preflight_api_returns_paper_report() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/v1/acceptance/preflight",
        params={"project_root": str(ROOT), "scope": "paper"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is True
    assert body["failed_count"] == 0
    assert {check["check_id"] for check in body["checks"]} == {"paper.preflight"}


def test_preflight_cli_returns_paper_report() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli_app,
        [
            "acceptance",
            "preflight",
            "--project-root",
            str(ROOT),
            "--scope",
            "paper",
            "--compact",
        ],
    )

    assert result.exit_code == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["passed"] is True
    assert body["failed_count"] == 0
    assert {check["check_id"] for check in body["checks"]} == {"paper.preflight"}
