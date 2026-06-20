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
