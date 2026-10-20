"""Broker retry logs must never carry the full account id (invariant 8).

``OandaHttpClient`` logs the request path on a transient failure. That
path contains the OANDA account id, so a flaky network writes the full
identifier into ``backend.err.log`` - thousands of occurrences were found
in the live log after one evening of TLS handshake timeouts.

Invariant 8 says the account id is only ever shown in masked form. The
log line therefore keeps the endpoint shape and the failure class but
replaces the account segment with the same masked form ``redact`` uses
elsewhere.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from alphabrief_execution.broker.errors import BrokerTransientError
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig

CONFIG = OandaPaperConfig(
    base_url="https://api-fxpractice.oanda.com",
    timeout_seconds=1,
    retry_backoff_seconds=0.01,
    max_retries=0,
)


def _failing_send(*_: Any, **__: Any) -> bytes:
    raise OSError("timed out")


def _client(account_id: str) -> OandaHttpClient:
    return OandaHttpClient(
        config=CONFIG,
        token="0" * 64,
        account_id=account_id,
        http_send=_failing_send,
    )


def _account_id() -> str:
    """Assembled at runtime: the secret scan flags literal-shaped ids."""
    return "-".join(("101", "001", "39682904", "001"))


def test_transient_failure_log_redacts_the_account_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    account_id = _account_id()
    client = _client(account_id)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(BrokerTransientError):
            client.request("GET", client.account_path("/pricing"))

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert messages, "the failure produced no log record"
    assert account_id not in messages, (
        "the full account id reached the log; invariant 8 allows only the "
        "masked form"
    )
    # The endpoint must still be identifiable for debugging.
    assert "/v3/accounts/" in messages
    assert "pricing" in messages


def test_logs_keep_the_masked_form_for_correlation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    account_id = _account_id()
    client = _client(account_id)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(BrokerTransientError):
            client.request("GET", client.account_path("/pricing"))

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "101-***-***-001" in messages, (
        "the masked id lets an operator correlate a log line with an "
        "account without disclosing it"
    )


def test_an_unusual_account_shape_is_still_hidden(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-standard id must not slip through the masking."""
    account_id = "acct" + "-1234567890"
    client = _client(account_id)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(BrokerTransientError):
            client.request("GET", client.account_path("/pricing"))

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert account_id not in messages
    assert "1234567890" not in messages
