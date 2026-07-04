"""Core configuration loading for AlphaBrief.

This module reads explicit `ALPHABRIEF_` environment variables into a small
settings object. It does not read `.env` files or include secret fields.
"""

from collections.abc import Mapping
from os import environ as os_environ
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AlphaBriefEnv = Literal["local", "test", "dev", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


_ENV_PREFIX = "ALPHABRIEF_"
_ENV_TO_FIELD = {
    f"{_ENV_PREFIX}ENV": "env",
    f"{_ENV_PREFIX}LOG_LEVEL": "log_level",
    f"{_ENV_PREFIX}LIVE_TRADING_ENABLED": "live_trading_enabled",
    f"{_ENV_PREFIX}DATA_DIR": "data_dir",
    f"{_ENV_PREFIX}REPORTS_DIR": "reports_dir",
    f"{_ENV_PREFIX}AUDIT_LOG_DIR": "audit_log_dir",
    f"{_ENV_PREFIX}EXECUTION_POLICY_FILE": "execution_policy_file",
}
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


class AppSettings(BaseModel):
    """Application settings shared by AlphaBrief modules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    env: AlphaBriefEnv = "local"
    log_level: LogLevel = "INFO"
    live_trading_enabled: bool = False
    data_dir: Path = Field(default_factory=lambda: Path("data/local"))
    reports_dir: Path = Field(default_factory=lambda: Path("reports/generated"))
    audit_log_dir: Path = Field(default_factory=lambda: Path("reports/audit"))
    execution_policy_file: Path = Field(
        default_factory=lambda: Path("config/paper_execution_policy.yaml")
    )

    @field_validator("env", mode="before")
    @classmethod
    def normalize_env(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("live_trading_enabled", mode="before")
    @classmethod
    def parse_explicit_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in _TRUE_VALUES:
                return True
            if normalized in _FALSE_VALUES:
                return False
        raise ValueError(
            "boolean settings must be explicit: true/false, 1/0, yes/no, on/off"
        )


def load_settings(environ: Mapping[str, str] | None = None) -> AppSettings:
    """Load AlphaBrief settings from environment variables.

    Unknown environment variables are ignored so secrets cannot be silently
    attached to the settings object.
    """

    source = os_environ if environ is None else environ
    values: dict[str, Any] = {
        field_name: source[env_name]
        for env_name, field_name in _ENV_TO_FIELD.items()
        if env_name in source
    }
    return AppSettings(**values)


# ---------------------------------------------------------------------------
# .env file auto-loading
# ---------------------------------------------------------------------------


def load_env_file(
    path: Path | str | None = None,
    *,
    override: bool = False,
) -> Path | None:
    """Load a dotenv file into ``os.environ``.

    Args:
        path: Absolute or relative path to a dotenv file. ``None`` walks up
            from the current working directory to find a ``.env`` at a
            project root (the first directory containing ``pyproject.toml``).
        override: When ``True``, values from the dotenv file overwrite
            existing environment variables. The default is ``False`` so
            explicit shell exports always win.

    Returns:
        The resolved path to the dotenv file that was loaded, or ``None``
        when no file was found or auto-load was suppressed.

    Notes:
        The auto-load path (when ``path is None``) is automatically
        suppressed while pytest is running, so a project's real ``.env``
        cannot leak into unit-test processes. Tests that explicitly want
        to load a dotenv file should pass ``path`` directly or set
        ``ALPHABRIEF_NO_AUTO_LOAD_ENV=1``.
    """
    if path is None and _auto_load_is_suppressed():
        return None

    resolved: Path | None = None
    if path is None:
        resolved = _discover_env_file()
    else:
        candidate = Path(path)
        resolved = candidate if candidate.is_file() else None

    if resolved is None:
        return None

    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    load_dotenv(resolved, override=override)
    return resolved


def _auto_load_is_suppressed() -> bool:
    """Return ``True`` when the auto-load should be skipped.

    Three conditions suppress the auto-load:

    1. ``PYTEST_CURRENT_TEST`` — pytest sets this for every test, so a
       real ``.env`` never leaks into unit tests.
    2. ``pytest`` in ``sys.modules`` — pytest imports test modules
       before ``PYTEST_CURRENT_TEST`` exists, so this catches collection.
    3. ``ALPHABRIEF_NO_AUTO_LOAD_ENV=1`` — explicit operator override for
       ad-hoc debugging or for sub-processes that must run with a clean
       environment.
    """
    import os
    import sys

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    if "pytest" in sys.modules:
        return True
    if os.environ.get("ALPHABRIEF_NO_AUTO_LOAD_ENV", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    return False


def _discover_env_file() -> Path | None:
    """Walk up from cwd and ``__file__`` to find the project's ``.env``.

    Discovery happens in two passes:

    1. ``Path.cwd()`` and its ancestors — for the common case where the
       operator runs from the project root or a sub-directory.
    2. This module's directory and its ancestors — so operators running
       from outside the checkout (e.g. via an editable install invoked
       from anywhere) still find the project's ``.env``.
    """

    search_roots: list[Path] = [Path.cwd(), *Path.cwd().parents]
    search_roots.extend(Path(__file__).resolve().parents)
    for directory in search_roots:
        env_path = directory / ".env"
        if env_path.is_file():
            return env_path
    return None
