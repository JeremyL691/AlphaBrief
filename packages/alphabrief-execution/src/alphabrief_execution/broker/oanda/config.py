"""OANDA Paper adapter configuration.

Non-secret configuration is loaded from ``config/oanda_paper.yaml``.
Credentials (access token and account ID) are read from environment
variables only:

- ``ALPHABRIEF_OANDA_TOKEN``
- ``ALPHABRIEF_OANDA_ACCOUNT_ID``

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

#: Default OANDA v20 practice endpoint.
DEFAULT_BASE_URL = "https://api-fxpractice.oanda.com"

#: Default per-request timeout in seconds.
DEFAULT_TIMEOUT_SECONDS = 5.0

#: Default max retries for idempotent GET calls. POST/PUT/DELETE are never retried.
DEFAULT_MAX_RETRIES = 3

#: Default base backoff (seconds) for exponential retry.
DEFAULT_RETRY_BACKOFF_SECONDS = 0.25

#: Env var name for the OANDA bearer token.
ENV_TOKEN = "ALPHABRIEF_OANDA_TOKEN"

#: Env var name for the OANDA account ID.
ENV_ACCOUNT_ID = "ALPHABRIEF_OANDA_ACCOUNT_ID"

#: Keys that must NEVER appear in the YAML.
_FORBIDDEN_SECRET_KEYS: frozenset[str] = frozenset(
    {"key", "secret", "api_key", "api_secret", "password", "token", "account_id"}
)


@dataclass(frozen=True)
class OandaPaperConfig:
    """Loaded non-secret configuration for the OANDA Paper adapter."""

    base_url: str
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    allow_insecure_base_url: bool = False

    def __post_init__(self) -> None:
        """Validate paper-only transport settings."""
        if not self.base_url.startswith("https://"):
            if not self.allow_insecure_base_url:
                raise ValueError(
                    "oanda_paper.base_url must use https:// scheme, "
                    f"got {self.base_url!r}"
                )
            if "fxtrade" in self.base_url.lower() or "live" in self.base_url.lower():
                raise ValueError(
                    "oanda_paper.base_url must not point at live trading — paper only"
                )
        if "fxtrade" in self.base_url.lower() or "live" in self.base_url.lower():
            raise ValueError(
                "oanda_paper.base_url must not point at live trading — paper only"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("oanda_paper.timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("oanda_paper.max_retries must be non-negative")
        if self.retry_backoff_seconds <= 0:
            raise ValueError("oanda_paper.retry_backoff_seconds must be positive")


def load_oanda_paper_config(path: Path | str) -> OandaPaperConfig:
    """Load OANDA Paper configuration from a YAML file.

    Args:
        path: YAML file containing non-secret adapter settings.

    Returns:
        Parsed and validated OANDA Paper configuration.

    Raises:
        ValueError: If the file cannot be read, is not a YAML mapping, or
            contains forbidden secret keys.
    """
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(
            f"unable to read oanda_paper config {config_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"invalid YAML oanda_paper config {config_path}: {exc}"
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("oanda_paper config must be a YAML mapping")

    _assert_no_secrets(raw, source=config_path)

    return OandaPaperConfig(
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
                f"oanda_paper config {source} contains forbidden secret field {key!r}; "
                f"read credentials from env vars ({ENV_TOKEN} / "
                f"{ENV_ACCOUNT_ID}) instead"
            )


def read_oanda_credentials() -> tuple[str, str]:
    """Return (token, account_id) from environment, or raise BrokerAuthError.

    Never returns a placeholder or empty string — adapters must fail
    loudly when credentials are missing.
    """
    token = os.environ.get(ENV_TOKEN, "").strip()
    account_id = os.environ.get(ENV_ACCOUNT_ID, "").strip()
    if not token or not account_id:
        raise BrokerAuthError(
            f"missing OANDA credentials: set {ENV_TOKEN} and {ENV_ACCOUNT_ID}"
        )
    return token, account_id


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENV_ACCOUNT_ID",
    "ENV_TOKEN",
    "OandaPaperConfig",
    "load_oanda_paper_config",
    "read_oanda_credentials",
]
