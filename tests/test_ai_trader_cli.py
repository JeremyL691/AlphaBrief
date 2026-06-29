"""Tests for the ``alphabrief ai`` CLI subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_cli.ai_commands import ai_app  # noqa: F401  (import side-effects)
from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))


class TestAiStatus:
    def test_help(self) -> None:
        res = runner.invoke(app, ["ai", "status", "--help"])
        assert res.exit_code == 0

    def test_status_default(self) -> None:
        res = runner.invoke(app, ["ai", "status", "--compact"])
        assert res.exit_code == 0
        import json as _json

        data = _json.loads(res.stdout)
        assert data["ai_trading_enabled"] is False
        assert "discipline" in data

    def test_status_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        res = runner.invoke(app, ["ai", "status", "--compact"])
        assert res.exit_code == 0
        import json as _json

        data = _json.loads(res.stdout)
        assert data["ai_trading_enabled"] is True


class TestAiRun:
    def test_disabled_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ALPHABRIEF_AI_TRADING_ENABLED", raising=False)
        res = runner.invoke(
            app,
            ["ai", "run", "--symbols", "SPY"],
        )
        assert res.exit_code == 1
        assert "ALPHABRIEF_AI_TRADING_ENABLED" in (
            res.stderr + res.stdout
        )

    def test_live_unlocked_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        monkeypatch.setenv("ALPHABRIEF_LIVE_TRADING_ENABLED", "true")
        res = runner.invoke(
            app,
            ["ai", "run", "--symbols", "SPY"],
        )
        assert res.exit_code == 1
        assert "paper-only" in (res.stderr + res.stdout).lower()

    def test_run_records_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        res = runner.invoke(
            app,
            ["ai", "run", "--symbols", "SPY,QQQ", "--compact"],
        )
        assert res.exit_code == 0, res.stdout
        import json as _json

        data = _json.loads(res.stdout)
        assert "cycle_id" in data
        assert data["plan_count"] >= 0

    def test_invalid_reference_prices_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        res = runner.invoke(
            app,
            [
                "ai",
                "run",
                "--symbols",
                "SPY",
                "--reference-prices",
                "{not-json",
            ],
        )
        assert res.exit_code == 1

    def test_empty_symbols_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        res = runner.invoke(
            app, ["ai", "run", "--symbols", ",,, "]
        )
        assert res.exit_code == 1


class TestAiHistory:
    def test_history_empty(self) -> None:
        res = runner.invoke(app, ["ai", "history", "--compact"])
        assert res.exit_code == 0
        import json as _json

        data = _json.loads(res.stdout)
        assert data["cycles"] == []

    def test_history_after_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        runner.invoke(app, ["ai", "run", "--symbols", "SPY", "--compact"])
        res = runner.invoke(app, ["ai", "history", "--compact"])
        assert res.exit_code == 0
        import json as _json

        data = _json.loads(res.stdout)
        assert len(data["cycles"]) >= 1


class TestAiShow:
    def test_missing_cycle_returns_error(self) -> None:
        res = runner.invoke(
            app, ["ai", "show", "aic_does_not_exist"]
        )
        assert res.exit_code == 1

    def test_show_after_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        run_res = runner.invoke(
            app, ["ai", "run", "--symbols", "SPY", "--compact"]
        )
        import json as _json

        cycle_id = _json.loads(run_res.stdout)["cycle_id"]
        res = runner.invoke(app, ["ai", "show", cycle_id, "--compact"])
        assert res.exit_code == 0
        data = _json.loads(res.stdout)
        assert data["cycle_id"] == cycle_id


class TestAiRules:
    def test_rules(self) -> None:
        res = runner.invoke(app, ["ai", "rules", "--compact"])
        assert res.exit_code == 0
        import json as _json

        data = _json.loads(res.stdout)
        assert data["prompt_version"] == "aitrader-v1"
        assert data["roles"] == [
            "technical",
            "fundamental",
            "risk",
            "manager",
        ]