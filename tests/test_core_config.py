from pathlib import Path

import pytest
from alphabrief_core import AppSettings, load_env_file, load_settings
from pydantic import ValidationError


def test_load_settings_defaults_live_trading_to_false() -> None:
    settings = load_settings({})

    assert settings.env == "local"
    assert settings.log_level == "INFO"
    assert settings.live_trading_enabled is False
    assert settings.data_dir == Path("data/local")
    assert settings.reports_dir == Path("reports/generated")
    assert settings.audit_log_dir == Path("reports/audit")


def test_env_example_keeps_live_trading_disabled_by_default() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "ALPHABRIEF_LIVE_TRADING_ENABLED=false" in env_example


def test_load_settings_accepts_explicit_environment_values() -> None:
    settings = load_settings(
        {
            "ALPHABRIEF_ENV": "TEST",
            "ALPHABRIEF_LOG_LEVEL": "debug",
            "ALPHABRIEF_LIVE_TRADING_ENABLED": "YES",
            "ALPHABRIEF_DATA_DIR": "/tmp/alphabrief/data",
            "ALPHABRIEF_REPORTS_DIR": "custom/reports",
            "ALPHABRIEF_AUDIT_LOG_DIR": "custom/audit",
        }
    )

    assert settings.env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.live_trading_enabled is True
    assert settings.data_dir == Path("/tmp/alphabrief/data")
    assert settings.reports_dir == Path("custom/reports")
    assert settings.audit_log_dir == Path("custom/audit")


def test_load_settings_rejects_invalid_env() -> None:
    with pytest.raises(ValidationError):
        load_settings({"ALPHABRIEF_ENV": "staging"})


def test_load_settings_rejects_invalid_log_level() -> None:
    with pytest.raises(ValidationError):
        load_settings({"ALPHABRIEF_LOG_LEVEL": "TRACE"})


def test_load_settings_rejects_implicit_bool_values() -> None:
    with pytest.raises(ValidationError, match="boolean settings"):
        load_settings({"ALPHABRIEF_LIVE_TRADING_ENABLED": "maybe"})


def test_app_settings_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AppSettings.model_validate({"api_key": "secret"})


def test_unknown_environment_variables_are_not_attached_to_settings() -> None:
    settings = load_settings(
        {
            "ALPHABRIEF_LIVE_TRADING_ENABLED": "false",
            "ALPHABRIEF_PROVIDER_API_KEY": "secret",
            "BROKER_KEY": "secret",
        }
    )

    assert not hasattr(settings, "api_key")
    assert not hasattr(settings, "provider_api_key")
    assert settings.live_trading_enabled is False


# ---------------------------------------------------------------------------
# .env auto-loading
# ---------------------------------------------------------------------------


def test_load_env_file_loads_explicit_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "fixture.env"
    env_path.write_text(
        "ALPHABRIEF_LOG_LEVEL=WARNING\nEXTRA_IGNORED_KEY=1\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ALPHABRIEF_LOG_LEVEL", raising=False)

    loaded = load_env_file(env_path)

    assert loaded == env_path
    import os

    assert os.environ["ALPHABRIEF_LOG_LEVEL"] == "WARNING"


def test_load_env_file_does_not_override_existing_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "fixture.env"
    env_path.write_text("ALPHABRIEF_LOG_LEVEL=WARNING\n", encoding="utf-8")
    monkeypatch.setenv("ALPHABRIEF_LOG_LEVEL", "ERROR")

    loaded = load_env_file(env_path)

    import os

    assert loaded == env_path
    assert os.environ["ALPHABRIEF_LOG_LEVEL"] == "ERROR"


def test_load_env_file_returns_none_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``monkeypatch.chdir`` requires an existing directory.
    monkeypatch.chdir(tmp_path)

    assert load_env_file(tmp_path / "absent.env") is None
