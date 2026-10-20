"""The reviewed model configuration must load from any working directory.

``config/alphabrief.yaml`` is operator-owned and reviewer-reviewed. The
LaunchAgent sets ``WorkingDirectory`` to the data directory, so the
backend starts outside the checkout. The loader resolved its path from
``Path.cwd()`` only, failed to find the file and silently returned
``ModelSettings()`` defaults.

That fallback is dangerous in two ways:

* the primary channel became ``chatgpt_plan`` instead of the reviewed
  ``openrouter_free``, so the deployment ran a different channel than the
  one that was reviewed;
* the daily call limit became the chatgpt default (150) instead of the
  reviewed free-channel cap (1000), quietly changing the model budget.

A missing file must therefore mean "reviewed defaults", but an existing
file must be found regardless of the process's working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_models.channels import load_model_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_config_is_found_from_an_unrelated_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon starting in the data directory must still read the config."""
    monkeypatch.chdir(tmp_path)

    settings = load_model_settings()

    assert settings.primary_channel == "openrouter_free", (
        "the loader fell back to defaults because it only searched the "
        "working directory; the LaunchAgent runs from the data directory"
    )
    assert settings.primary_model is not None
    assert settings.primary_model.endswith(":free")
    assert settings.daily_call_limit == 1000


def test_config_is_found_when_a_relative_path_is_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The declared relative path keeps working from elsewhere."""
    monkeypatch.chdir(tmp_path)

    settings = load_model_settings(Path("config/alphabrief.yaml"))

    assert settings.primary_channel == "openrouter_free"


def test_an_absolute_path_wins_over_discovery(tmp_path: Path) -> None:
    target = tmp_path / "custom.yaml"
    target.write_text(
        'model:\n  primary_channel: chatgpt_plan\n  daily_cost_limit_usd: "2.00"\n',
        encoding="utf-8",
    )

    settings = load_model_settings(target)

    assert settings.primary_channel == "chatgpt_plan"
    assert settings.daily_call_limit == 150


def test_a_missing_file_still_yields_reviewed_defaults(tmp_path: Path) -> None:
    """No file anywhere is the documented default, not an error."""
    settings = load_model_settings(tmp_path / "absent.yaml")

    assert settings.primary_channel == "chatgpt_plan"
    assert settings.fallback_enabled is False


def test_the_repository_config_matches_the_reviewed_free_channel() -> None:
    """A guard against the shipped file drifting from the reviewed policy."""
    settings = load_model_settings(REPO_ROOT / "config/alphabrief.yaml")

    assert settings.primary_channel == "openrouter_free"
    assert settings.fallback_enabled is False
    assert settings.daily_cost_limit_usd == 0
