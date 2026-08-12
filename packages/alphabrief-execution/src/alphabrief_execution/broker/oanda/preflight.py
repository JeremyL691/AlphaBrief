"""Fail-closed OANDA practice account preflight (M04-W01).

``run_account_preflight`` validates the configured practice account
before any catalog sync or execution: credentials must be present, the
endpoint is the constant practice host, the response must belong to the
configured account, the account must be tradeable, and the payload must
be well-formed. The resulting :class:`OandaAccountProfile` carries a
scrubbed account correlation hash (SHA-256 of the account ID — never the
raw ID), Decimal money fields, capability flags, and a UTC retrieval
timestamp; the token is never part of any profile or exception.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.errors import BrokerAuthError
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig

#: Failure classification for preflight errors (never carries secrets).
PreflightFailure = (
    "missing_credentials",
    "invalid_credentials",
    "live_host",
    "account_mismatch",
    "not_tradeable",
    "malformed_response",
)


class AccountPreflightError(RuntimeError):
    """A classified account preflight failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"account preflight failed ({kind}): {detail}")


class OandaAccountProfile(BaseModel):
    """One validated account preflight profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id_hash: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    balance: Decimal
    nav: Decimal
    margin_available: Decimal
    margin_used: Decimal
    position_value: Decimal
    open_trade_count: int = Field(ge=0)
    open_position_count: int = Field(ge=0)
    pending_order_count: int = Field(ge=0)
    guaranteed_stop_loss_mode: str = Field(min_length=1)
    tradeable: bool
    retrieved_at: datetime


def _scrub_account_id(account_id: str) -> str:
    """Return a non-reversible correlation hash of the account ID."""
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (TypeError, ValueError) as exc:
        raise AccountPreflightError(
            "malformed_response", f"invalid {field}: {value!r}"
        ) from exc


def _int(value: Any, field: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise AccountPreflightError(
            "malformed_response", f"invalid {field}: {value!r}"
        ) from exc


def run_account_preflight(
    config: OandaPaperConfig,
    *,
    token: str,
    account_id: str,
    http_send: Callable[..., bytes] | None = None,
) -> OandaAccountProfile:
    """Validate the configured OANDA practice account, fail closed.

    Raises :class:`AccountPreflightError` with a classified kind for
    missing credentials, invalid credentials, a live host, an account
    mismatch, a non-tradeable account, or a malformed response. The
    token and the complete account ID never appear in the profile, the
    exception, or any log produced here.
    """
    if not token or not account_id:
        raise AccountPreflightError(
            "missing_credentials",
            "OANDA token and account ID are required",
        )
    if "fxtrade" in config.base_url.lower() or "live" in config.base_url.lower():
        raise AccountPreflightError(
            "live_host", "preflight refuses a live OANDA endpoint"
        )

    client = OandaHttpClient(
        config=config,
        http_send=http_send,
        token=token,
        account_id=account_id,
    )
    try:
        response = client.request("GET", f"/v3/accounts/{account_id}")
    except BrokerAuthError as exc:
        raise AccountPreflightError(
            "invalid_credentials", "OANDA rejected the credentials"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — classified transport failure
        raise AccountPreflightError(
            "malformed_response", f"account request failed: {type(exc).__name__}"
        ) from exc

    body = response.json_body
    if not isinstance(body, dict) or not isinstance(body.get("account"), dict):
        raise AccountPreflightError(
            "malformed_response", "account response is not a JSON object"
        )
    account: dict[str, Any] = body["account"]

    returned_id = str(account.get("id", "")).strip()
    if returned_id != account_id:
        raise AccountPreflightError(
            "account_mismatch",
            "response account does not match the configured account",
        )

    currency = str(account.get("currency", "")).strip()
    balance = _decimal(account.get("balance"), "balance")
    nav = _decimal(account.get("NAV", account.get("balance")), "NAV")
    margin_available = _decimal(
        account.get("marginAvailable", "0"), "marginAvailable"
    )
    margin_used = _decimal(account.get("marginUsed", "0"), "marginUsed")
    position_value = _decimal(account.get("positionValue", "0"), "positionValue")
    margin_rate = _decimal(account.get("marginRate", "0"), "marginRate")

    if not currency or balance <= 0 or margin_rate <= 0:
        raise AccountPreflightError(
            "not_tradeable",
            "account is missing currency, balance, or margin rate",
        )

    gsl_mode = str(account.get("guaranteedStopLossOrderMode", "DISABLED")).strip()
    return OandaAccountProfile(
        account_id_hash=_scrub_account_id(account_id),
        currency=currency,
        balance=balance,
        nav=nav,
        margin_available=margin_available,
        margin_used=margin_used,
        position_value=position_value,
        open_trade_count=_int(account.get("openTradeCount", 0), "openTradeCount"),
        open_position_count=_int(
            account.get("openPositionCount", 0), "openPositionCount"
        ),
        pending_order_count=_int(
            account.get("pendingOrderCount", 0), "pendingOrderCount"
        ),
        guaranteed_stop_loss_mode=gsl_mode,
        tradeable=True,
        retrieved_at=datetime.now(UTC),
    )


__all__ = [
    "AccountPreflightError",
    "OandaAccountProfile",
    "run_account_preflight",
]
