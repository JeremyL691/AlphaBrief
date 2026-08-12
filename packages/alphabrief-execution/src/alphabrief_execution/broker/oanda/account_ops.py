"""OANDA account operations port (M06-W04).

Account summary and account changes with exact OANDA semantics: balance,
NAV, unrealized PnL, margins, open counts, and the durable
``sinceTransactionID`` cursor. Broker transaction IDs stay distinct and
Decimal-safe; missing, malformed, or invalid cursors fail closed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.errors import (
    BrokerNotFoundError,
    BrokerProtocolError,
    BrokerRejectError,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient

DEFAULT_SINCE_TRANSACTION_ID = "0"


class AccountOperationError(RuntimeError):
    """A classified account operation failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"account operation failed ({kind}): {detail}")


class AccountSummaryResult(BaseModel):
    """One typed account summary snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    balance: Decimal
    nav: Decimal
    unrealized_pl: Decimal
    margin_used: Decimal
    margin_available: Decimal
    open_order_count: int
    open_trade_count: int
    open_position_count: int
    last_transaction_id: str
    request_id: str = Field(min_length=1)


class AccountChangesResult(BaseModel):
    """One typed account-changes page since a durable cursor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    since_transaction_id: str
    last_transaction_id: str
    orders_created: int
    orders_cancelled: int
    orders_filled: int
    orders_triggered: int
    trades_opened: int
    trades_reduced: int
    trades_closed: int
    positions_closed: int
    positions_reduced: int
    transactions: int
    balance: Decimal
    nav: Decimal
    unrealized_pl: Decimal
    request_id: str = Field(min_length=1)


class AccountOpsClient:
    """Account summary and changes port over the OANDA practice client."""

    def __init__(self, client: OandaHttpClient) -> None:
        self._client = client

    def account_summary(
        self,
        *,
        request_id: str | None = None,
    ) -> AccountSummaryResult:
        """Fetch one typed account summary snapshot."""
        try:
            response = self._client.request(
                "GET", self._client.account_path("/summary")
            )
        except BrokerNotFoundError as exc:
            raise AccountOperationError(
                "account_not_found", "account is missing"
            ) from exc
        except BrokerRejectError as exc:
            raise AccountOperationError("rejected", exc.reason) from exc
        except BrokerProtocolError as exc:
            raise AccountOperationError("protocol_error", str(exc)) from exc
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("account"), dict):
            raise AccountOperationError(
                "protocol_error", "summary response is not JSON"
            )
        account = body["account"]
        try:
            return AccountSummaryResult(
                account_id=str(account.get("id", "")).strip(),
                currency=str(account.get("currency", "")).strip(),
                balance=_decimal(account.get("balance", "0")),
                nav=_decimal(account.get("NAV", "0")),
                unrealized_pl=_decimal(account.get("unrealizedPL", "0")),
                margin_used=_decimal(account.get("marginUsed", "0")),
                margin_available=_decimal(account.get("marginAvailable", "0")),
                open_order_count=_count(account.get("openOrderCount")),
                open_trade_count=_count(account.get("openTradeCount")),
                open_position_count=_count(account.get("openPositionCount")),
                last_transaction_id=str(
                    account.get("lastTransactionID", "")
                ).strip(),
                request_id=request_id or "summary",
            )
        except (KeyError, ValueError) as exc:
            raise AccountOperationError(
                "protocol_error", f"summary parse failed: {exc}"
            ) from exc

    def account_changes(
        self,
        since_transaction_id: str = DEFAULT_SINCE_TRANSACTION_ID,
        *,
        request_id: str | None = None,
    ) -> AccountChangesResult:
        """Fetch account changes since a durable broker cursor.

        The cursor is an OANDA transaction ID (digits only, never a local
        timestamp). ``last_transaction_id`` is returned separately so a
        failed consumer can never advance the cursor past unseen
        transactions.
        """
        if not since_transaction_id.isdigit():
            raise AccountOperationError(
                "invalid_cursor", "since_transaction_id must be a digit string"
            )
        try:
            response = self._client.request(
                "GET",
                self._client.account_path("/changes"),
                params={"sinceTransactionID": since_transaction_id},
            )
        except BrokerNotFoundError as exc:
            raise AccountOperationError(
                "account_not_found", "account is missing"
            ) from exc
        except BrokerRejectError as exc:
            raise AccountOperationError("rejected", exc.reason) from exc
        except BrokerProtocolError as exc:
            raise AccountOperationError("protocol_error", str(exc)) from exc
        body = response.json_body
        if not isinstance(body, dict):
            raise AccountOperationError(
                "protocol_error", "changes response is not JSON"
            )
        changes = body.get("changes")
        state = body.get("state")
        if not isinstance(changes, dict) or not isinstance(state, dict):
            raise AccountOperationError(
                "protocol_error", "changes response missing changes/state"
            )
        account = state.get("account")
        if not isinstance(account, dict):
            raise AccountOperationError(
                "protocol_error", "changes response missing account state"
            )
        try:
            return AccountChangesResult(
                since_transaction_id=since_transaction_id,
                last_transaction_id=str(body.get("lastTransactionID", "")).strip(),
                orders_created=_count_list(changes.get("ordersCreated")),
                orders_cancelled=_count_list(changes.get("ordersCancelled")),
                orders_filled=_count_list(changes.get("ordersFilled")),
                orders_triggered=_count_list(changes.get("ordersTriggered")),
                trades_opened=_count_list(changes.get("tradesOpened")),
                trades_reduced=_count_list(changes.get("tradesReduced")),
                trades_closed=_count_list(changes.get("tradesClosed")),
                positions_closed=_count_list(changes.get("positionsClosed")),
                positions_reduced=_count_list(changes.get("positionsReduced")),
                transactions=_count_list(changes.get("transactions")),
                balance=_decimal(account.get("balance", "0")),
                nav=_decimal(account.get("NAV", "0")),
                unrealized_pl=_decimal(account.get("unrealizedPL", "0")),
                request_id=request_id or f"changes-{since_transaction_id}",
            )
        except (KeyError, ValueError) as exc:
            raise AccountOperationError(
                "protocol_error", f"changes parse failed: {exc}"
            ) from exc


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _count(value: Any) -> int:
    return int(str(value)) if str(value).strip().isdigit() else 0


def _count_list(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    return len(value)


__all__ = [
    "AccountChangesResult",
    "AccountOperationError",
    "AccountOpsClient",
    "AccountSummaryResult",
    "DEFAULT_SINCE_TRANSACTION_ID",
]
