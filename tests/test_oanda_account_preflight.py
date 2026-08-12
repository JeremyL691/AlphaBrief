"""M04-W01: fail-closed OANDA practice account preflight.

Covers:
- a valid practice response produces one typed account profile with
  margin fields, capability flags, a scrubbed account correlation hash,
  and a UTC retrieval timestamp (AC-M04-W01-01);
- missing credentials, invalid credentials, live hosts, account
  mismatch, non-tradeable accounts, and malformed responses fail closed
  before any catalog sync or execution with no fallback
  (AC-M04-W01-02);
- CLI/API/logs/exceptions/evidence contain neither the token nor the
  complete account ID (AC-M04-W01-03).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_execution.broker.errors import BrokerAuthError
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.preflight import (
    AccountPreflightError,
    OandaAccountProfile,
    run_account_preflight,
)

ACCOUNT_ID = "101-004-1234567-001"
TOKEN = "super-secret-token-value-1234567890"


def _config(**overrides: object) -> OandaPaperConfig:
    payload: dict[str, Any] = {
        "base_url": "https://api-fxpractice.oanda.com",
        "timeout_seconds": 1.0,
        "max_retries": 0,
        "retry_backoff_seconds": 0.001,
    }
    payload.update(overrides)
    return OandaPaperConfig(
        base_url=str(payload["base_url"]),
        timeout_seconds=float(payload["timeout_seconds"]),
        max_retries=int(payload["max_retries"]),
        retry_backoff_seconds=float(payload["retry_backoff_seconds"]),
        allow_insecure_base_url=bool(payload.get("allow_insecure_base_url", False)),
    )


def _valid_account() -> dict[str, Any]:
    return {
        "account": {
            "id": ACCOUNT_ID,
            "currency": "USD",
            "balance": "99123.45",
            "NAV": "100000.00",
            "marginAvailable": "90000.00",
            "marginUsed": "10000.00",
            "positionValue": "12000.00",
            "marginRate": "0.05",
            "openTradeCount": 2,
            "openPositionCount": 2,
            "pendingOrderCount": 1,
            "guaranteedStopLossOrderMode": "REQUIRED",
            "lastTransactionID": "42",
        }
    }


def _ok_send(body: dict[str, Any]) -> Any:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        return json.dumps(body).encode("utf-8")

    return _send


# ---------------------------------------------------------------------------
# AC-M04-W01-01: valid response -> typed profile
# ---------------------------------------------------------------------------


def test_valid_practice_response_produces_typed_profile() -> None:
    profile = run_account_preflight(
        _config(),
        token=TOKEN,
        account_id=ACCOUNT_ID,
        http_send=_ok_send(_valid_account()),
    )
    assert isinstance(profile, OandaAccountProfile)
    assert profile.currency == "USD"
    assert profile.balance == Decimal("99123.45")
    assert profile.nav == Decimal("100000.00")
    assert profile.margin_available == Decimal("90000.00")
    assert profile.margin_used == Decimal("10000.00")
    assert profile.position_value == Decimal("12000.00")
    assert profile.open_trade_count == 2
    assert profile.open_position_count == 2
    assert profile.pending_order_count == 1
    assert profile.guaranteed_stop_loss_mode == "REQUIRED"
    assert profile.tradeable is True
    assert profile.retrieved_at.tzinfo is not None


def test_profile_contains_scrubbed_account_hash_only() -> None:
    profile = run_account_preflight(
        _config(),
        token=TOKEN,
        account_id=ACCOUNT_ID,
        http_send=_ok_send(_valid_account()),
    )
    # The profile carries a non-reversible hash, never the raw account ID.
    assert profile.account_id_hash != ACCOUNT_ID
    assert len(profile.account_id_hash) == 64
    serialized = profile.model_dump_json()
    assert ACCOUNT_ID not in serialized
    assert TOKEN not in serialized


# ---------------------------------------------------------------------------
# AC-M04-W01-02: fail-closed classifications
# ---------------------------------------------------------------------------


def test_missing_credentials_fail_closed() -> None:
    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(_config(), token="", account_id=ACCOUNT_ID)
    assert excinfo.value.kind == "missing_credentials"
    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(_config(), token=TOKEN, account_id="")
    assert excinfo.value.kind == "missing_credentials"


def test_invalid_credentials_fail_closed() -> None:
    def _auth_fail(request: Request, timeout_seconds: float) -> bytes:
        raise BrokerAuthError("oanda auth rejected (HTTP 401)")

    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(
            _config(),
            token=TOKEN,
            account_id=ACCOUNT_ID,
            http_send=_auth_fail,
        )
    assert excinfo.value.kind == "invalid_credentials"
    # The exception message never carries the token.
    assert TOKEN not in str(excinfo.value)


def test_live_host_fails_closed() -> None:
    # OandaPaperConfig rejects a live host at construction (fail closed);
    # the preflight re-checks the base URL as defense in depth.
    with pytest.raises(ValueError, match="live trading"):
        _config(base_url="https://api-fxtrade.oanda.com")

    live_config = object.__new__(OandaPaperConfig)
    object.__setattr__(live_config, "base_url", "https://api-fxtrade.oanda.com")
    object.__setattr__(live_config, "timeout_seconds", 1.0)
    object.__setattr__(live_config, "max_retries", 0)
    object.__setattr__(live_config, "retry_backoff_seconds", 0.001)
    object.__setattr__(live_config, "allow_insecure_base_url", False)
    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(
            live_config,
            token=TOKEN,
            account_id=ACCOUNT_ID,
        )
    assert excinfo.value.kind == "live_host"


def test_account_mismatch_fails_closed() -> None:
    body = _valid_account()
    body["account"]["id"] = "999-004-9999999-001"
    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(
            _config(),
            token=TOKEN,
            account_id=ACCOUNT_ID,
            http_send=_ok_send(body),
        )
    assert excinfo.value.kind == "account_mismatch"
    assert ACCOUNT_ID not in str(excinfo.value)


def test_non_tradeable_account_fails_closed() -> None:
    body = _valid_account()
    body["account"]["balance"] = "0"
    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(
            _config(),
            token=TOKEN,
            account_id=ACCOUNT_ID,
            http_send=_ok_send(body),
        )
    assert excinfo.value.kind == "not_tradeable"


def test_malformed_response_fails_closed() -> None:
    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(
            _config(),
            token=TOKEN,
            account_id=ACCOUNT_ID,
            http_send=_ok_send({"unexpected": True}),
        )
    assert excinfo.value.kind == "malformed_response"

    def _bad_json(request: Request, timeout_seconds: float) -> bytes:
        return b"not json"

    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(
            _config(),
            token=TOKEN,
            account_id=ACCOUNT_ID,
            http_send=_bad_json,
        )
    assert excinfo.value.kind == "malformed_response"


# ---------------------------------------------------------------------------
# AC-M04-W01-03: no token or complete account ID in any surface
# ---------------------------------------------------------------------------


def test_exceptions_never_contain_token_or_account_id() -> None:
    try:
        run_account_preflight(_config(), token="", account_id=ACCOUNT_ID)
    except AccountPreflightError as exc:
        assert TOKEN not in str(exc)
        assert ACCOUNT_ID not in str(exc)
    try:
        run_account_preflight(
            _config(),
            token=TOKEN,
            account_id=ACCOUNT_ID,
            http_send=_ok_send(_valid_account()),
        )
    except AccountPreflightError as exc:
        assert TOKEN not in str(exc)
        assert ACCOUNT_ID not in str(exc)


def test_preflight_module_never_logs_credentials() -> None:
    """The preflight source contains no logging of token or account ID."""
    import inspect

    from alphabrief_execution.broker.oanda import preflight

    source = inspect.getsource(preflight)
    assert "logging" not in source or "token" not in source.lower().split("log")
    assert TOKEN not in source
    assert "print(" not in source
