"""Tests for model CLI subcommands (Phase 14 Round 5)."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.db import ModelEvalStore
from alphabrief_cli.model_commands import model_app
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path: Path) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    yield


# ---------------------------------------------------------------------------
# model evaluate
# ---------------------------------------------------------------------------


def test_evaluate_runs_and_prints_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "evaluate",
            "--model-id", "fake:fake-model",
            "--task", "daily_brief",
            "--dataset", "daily_brief_v1",
            "--sample-count", "2",
            "--compact",
        ],
    )
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout.strip())
    assert body["model_id"] == "fake:fake-model"
    assert body["task_type"] == "daily_brief"
    assert body["sample_count"] == 2


def test_evaluate_rejects_malformed_model_id() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "evaluate",
            "--model-id", "no-colon",
            "--task", "daily_brief",
        ],
    )
    assert result.exit_code != 0
    assert "provider:model" in result.stderr


def test_evaluate_rejects_unknown_dataset() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "evaluate",
            "--model-id", "fake:fake-model",
            "--task", "daily_brief",
            "--dataset", "nonexistent",
        ],
    )
    assert result.exit_code != 0
    assert "unknown dataset_id" in result.stderr


def test_evaluate_rejects_task_type_mismatch() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "evaluate",
            "--model-id", "fake:fake-model",
            "--task", "risk_review",
            "--dataset", "daily_brief_v1",
        ],
    )
    assert result.exit_code != 0
    assert "does not match" in result.stderr


def test_evaluate_persists_to_db(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(
        model_app,
        [
            "evaluate",
            "--model-id", "fake:fake-model",
            "--task", "daily_brief",
            "--dataset", "daily_brief_v1",
            "--sample-count", "1",
            "--compact",
        ],
    )
    db_dir = tmp_path / "alphabrief_db"
    db_dir.mkdir(parents=True, exist_ok=True)
    store = ModelEvalStore(db_path=db_dir / "alphabrief.db")
    try:
        records = store.get_evaluations(model_id="fake:fake-model")
        assert len(records) == 1
    finally:
        store.close()


# ---------------------------------------------------------------------------
# model performance
# ---------------------------------------------------------------------------


def test_performance_empty_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app, ["performance", "--model-id", "fake:fake-model"]
    )
    assert result.exit_code != 0
    assert "no evaluations" in result.stderr


def test_performance_rejects_malformed_model_id() -> None:
    runner = CliRunner()
    result = runner.invoke(model_app, ["performance", "--model-id", "nocolon"])
    assert result.exit_code != 0
    assert "provider:model" in result.stderr


def test_performance_returns_records(tmp_path: Path) -> None:
    db_dir = tmp_path / "alphabrief_db"
    db_dir.mkdir(parents=True, exist_ok=True)
    store = ModelEvalStore(db_path=db_dir / "alphabrief.db")
    try:
        store.save_evaluation(
            model_id="fake:fake-model",
            provider="fake",
            task_type="daily_brief",
            eval_dataset="daily_brief_v1",
            sample_count=5,
            schema_pass_rate=0.9,
        )
    finally:
        store.close()
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "performance",
            "--model-id", "fake:fake-model",
            "--task", "daily_brief",
            "--compact",
        ],
    )
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout.strip())
    assert isinstance(body, list)
    assert body[0]["schema_pass_rate"] == 0.9


# ---------------------------------------------------------------------------
# model route
# ---------------------------------------------------------------------------


def test_route_capability_only() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "route",
            "--task", "test",
            "--capabilities", "text_generation",
            "--compact",
        ],
    )
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout.strip())
    assert body["used_performance_data"] is False
    assert body["profile_id"] is not None


def test_route_uses_performance_data(tmp_path: Path) -> None:
    db_dir = tmp_path / "alphabrief_db"
    db_dir.mkdir(parents=True, exist_ok=True)
    store = ModelEvalStore(db_path=db_dir / "alphabrief.db")
    try:
        store.save_evaluation(
            model_id="anthropic:claude-3",
            provider="anthropic",
            task_type="daily_brief",
            eval_dataset="daily_brief_v1",
            sample_count=5,
            schema_pass_rate=0.95,
        )
    finally:
        store.close()
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "route",
            "--task", "daily_brief",
            "--capabilities", "text_generation,structured_output",
            "--compact",
        ],
    )
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout.strip())
    assert body["used_performance_data"] is True


def test_route_rejects_empty_capabilities() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        ["route", "--task", "test", "--capabilities", ""],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# model compare
# ---------------------------------------------------------------------------


def test_compare_prints_rows(tmp_path: Path) -> None:
    db_dir = tmp_path / "alphabrief_db"
    db_dir.mkdir(parents=True, exist_ok=True)
    store = ModelEvalStore(db_path=db_dir / "alphabrief.db")
    try:
        store.save_evaluation(
            model_id="fake:fake-model",
            provider="fake",
            task_type="daily_brief",
            eval_dataset="daily_brief_v1",
            sample_count=5,
            schema_pass_rate=0.85,
        )
    finally:
        store.close()
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "compare",
            "--model-ids", "fake:fake-model,anthropic:claude-3",
            "--task", "daily_brief",
            "--compact",
        ],
    )
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout.strip())
    assert len(body["rows"]) == 2
    by_model = {r["model_id"]: r for r in body["rows"]}
    assert by_model["fake:fake-model"]["has_data"] is True
    assert by_model["anthropic:claude-3"]["has_data"] is False


def test_compare_rejects_single_model() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "compare",
            "--model-ids", "fake:fake-model",
            "--task", "daily_brief",
        ],
    )
    assert result.exit_code != 0


def test_compare_rejects_malformed_model_id() -> None:
    runner = CliRunner()
    result = runner.invoke(
        model_app,
        [
            "compare",
            "--model-ids", "fake:fake-model,nocolon",
            "--task", "daily_brief",
        ],
    )
    assert result.exit_code != 0
    assert "provider:model" in result.stderr
