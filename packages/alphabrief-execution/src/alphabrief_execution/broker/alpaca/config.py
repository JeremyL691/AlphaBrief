"""Alpaca Paper adapter configuration.

Non-secret configuration is loaded from ``config/alpaca_paper.yaml``.
Credentials (API key, secret) are read from environment variables only:

- ``ALPHABRIEF_ALPACA_KEY``
- ``ALPHABRIEF_ALPACA_SECRET``

The YAML MUST NOT contain credentials. The loader asserts this.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from alphabrief_execution.broker.errors import BrokerAuthError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

#: Default Alpaca Paper endpoint. The live endpoint is intentionally not
#: exposed anywhere in this module - see AGENTS.md. This module is scheduled
#: for deletion in blueprint milestone M01.
DEFAULT_BASE_URL = "https://paper-api.alpaca.markets"

#: Default per-request timeout in seconds.
DEFAULT_TIMEOUT_SECONDS = 5.0

#: Default max retries for idempotent GET calls. POST is never retried.
DEFAULT_MAX_RETRIES = 3

#: Default base backoff (seconds) for exponential retry.
DEFAULT_RETRY_BACKOFF_SECONDS = 0.25

#: Env var name for the API key.
ENV_KEY = "ALPHABRIEF_ALPACA_KEY"

#: Env var name for the API secret.
ENV_SECRET = "ALPHABRIEF_ALPACA_SECRET"

#: Keys that must NEVER appear in the YAML.
_FORBIDDEN_SECRET_KEYS: frozenset[str] = frozenset(
    {"key", "secret", "api_key", "api_secret", "password", "token"}
)


@dataclass(frozen=True)
class AlpacaPaperConfig:
    """Loaded non-secret configuration for the Alpaca Paper adapter."""

    base_url: str
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    allow_insecure_base_url: bool = False

    def __post_init__(self) -> None:
        if not self.base_url.startswith("https://"):
            if not self.allow_insecure_base_url:
                raise ValueError(
                    "alpaca_paper.base_url must use https:// scheme, "
                    f"got {self.base_url!r}"
                )
            if "live" in self.base_url.lower():
                raise ValueError(
                    "alpaca_paper.base_url must not contain 'live' — paper only"
                )
        if "live" in self.base_url.lower():
            raise ValueError(
                "alpaca_paper.base_url must not contain 'live' — paper only"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("alpaca_paper.timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("alpaca_paper.max_retries must be non-negative")
        if self.retry_backoff_seconds <= 0:
            raise ValueError("alpaca_paper.retry_backoff_seconds must be positive")


def load_alpaca_paper_config(path: Path | str) -> AlpacaPaperConfig:
    """Load Alpaca Paper configuration from a YAML file.

    Raises ``ValueError`` if the file contains any forbidden secret key.
    """
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(
            f"unable to read alpaca_paper config {config_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"invalid YAML alpaca_paper config {config_path}: {exc}"
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("alpaca_paper config must be a YAML mapping")

    _assert_no_secrets(raw, source=config_path)

    return AlpacaPaperConfig(
        base_url=str(raw.get("base_url", DEFAULT_BASE_URL)),
        timeout_seconds=float(
            raw.get("request_timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        ),
        max_retries=int(raw.get("max_order_attempts", DEFAULT_MAX_RETRIES)),
        retry_backoff_seconds=float(
            raw.get("retry_backoff_seconds", DEFAULT_RETRY_BACKOFF_SECONDS)
        ),
    )


def _assert_no_secrets(raw: dict[str, Any], *, source: Path) -> None:
    for key in raw:
        if key.lower() in _FORBIDDEN_SECRET_KEYS:
            raise ValueError(
                f"alpaca_paper config {source} contains forbidden "
                f"secret field {key!r}; read credentials from env vars "
                f"({ENV_KEY} / {ENV_SECRET}) instead"
            )


def read_alpaca_credentials() -> tuple[str, str]:
    """Return (key, secret) from environment, or raise BrokerAuthError.

    Never returns a placeholder or empty string — adapters must fail
    loudly when credentials are missing.
    """
    key = os.environ.get(ENV_KEY, "").strip()
    secret = os.environ.get(ENV_SECRET, "").strip()
    if not key or not secret:
        raise BrokerAuthError(
            f"missing Alpaca credentials: set {ENV_KEY} and {ENV_SECRET}"
        )
    return key, secret


__all__ = [
    "AlpacaPaperConfig",
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENV_KEY",
    "ENV_SECRET",
    "load_alpaca_paper_config",
    "read_alpaca_credentials",
]
