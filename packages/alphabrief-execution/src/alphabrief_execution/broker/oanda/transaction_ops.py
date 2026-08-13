"""OANDA transaction details, ranges, and cursor primitives (M06-W05).

Transaction get, ID-range, paginated-range, and since-ID primitives for
durable reconciliation. OANDA transaction IDs are the only cursor
authority — local timestamps are never substituted and never accepted.
Output is normalized deterministically (deduplicated, broker-ID ordered)
with explicit gap signals for empty, overlapping, duplicate,
out-of-order, or missing ranges. Cursor candidates are returned
separately from durable advancement: this port holds no durable cursor,
so a failed consumer can never acknowledge unseen transactions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.errors import BrokerNotFoundError
from alphabrief_execution.broker.oanda.client import OandaHttpClient

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000
MAX_PAGES = 50


class TransactionOperationError(RuntimeError):
    """A classified transaction operation failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"transaction operation failed ({kind}): {detail}")


class TransactionResult(BaseModel):
    """One typed transaction with broker-ID authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: str = Field(min_length=1)
    transaction_type: str = Field(min_length=1)
    time: datetime | None = None
    instrument: str | None = None
    units: Decimal | None = None
    price: Decimal | None = None
    realized_pl: Decimal | None = None
    financing: Decimal | None = None
    request_id: str = Field(min_length=1)


class TransactionGap(BaseModel):
    """One explicit missing-ID span."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gap_from: str
    gap_to: str


class TransactionRangeResult(BaseModel):
    """One normalized, gap-signaled transaction window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transactions: tuple[TransactionResult, ...]
    declared_from: str | None = None
    declared_to: str | None = None
    cursor_candidate: str | None = None
    gaps: tuple[TransactionGap, ...]
    duplicate_count: int
    request_id: str = Field(min_length=1)


class TransactionOpsClient:
    """Transaction primitives over the OANDA practice client."""

    def __init__(self, client: OandaHttpClient) -> None:
        self._client = client

    def get_transaction(
        self,
        transaction_id: str,
        *,
        request_id: str | None = None,
    ) -> TransactionResult:
        """Fetch one transaction detail; unknown IDs fail closed."""
        if not transaction_id.isdigit():
            raise TransactionOperationError(
                "invalid_cursor", "transaction_id must be a digit string"
            )
        try:
            response = self._client.request(
                "GET",
                self._client.account_path(f"/transactions/{_path(transaction_id)}"),
            )
        except BrokerNotFoundError as exc:
            raise TransactionOperationError(
                "transaction_not_found", transaction_id
            ) from exc
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("transaction"), dict):
            raise TransactionOperationError(
                "protocol_error", "get response is not JSON"
            )
        try:
            return _transaction_from_row(
                body["transaction"],
                request_id=request_id or f"get-{transaction_id}",
            )
        except (KeyError, ValueError) as exc:
            raise TransactionOperationError(
                "protocol_error", f"transaction parse failed: {exc}"
            ) from exc

    def transaction_range(
        self,
        from_id: str,
        to_id: str,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        request_id: str | None = None,
    ) -> TransactionRangeResult:
        """Fetch an inclusive broker-ID range with gap signaling.

        ``from_id`` and ``to_id`` are OANDA transaction IDs (digits
        only); the declared range is echoed back so the caller's window
        is always explicit.
        """
        declared_from = _validate_id(from_id, field="from_id")
        declared_to = _validate_id(to_id, field="to_id")
        if declared_from > declared_to:
            raise TransactionOperationError(
                "invalid_range", "from_id must not exceed to_id"
            )
        _validate_page_size(page_size)
        rows, duplicates = self._fetch_idrange(
            from_id, to_id, page_size=page_size
        )
        return _normalize(
            rows,
            duplicates=duplicates,
            expected_start=declared_from,
            declared_from=from_id,
            declared_to=to_id,
            request_id=request_id or f"range-{from_id}-{to_id}",
        )

    def transactions_since(
        self,
        since_id: str,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        request_id: str | None = None,
    ) -> TransactionRangeResult:
        """Fetch transactions strictly after ``since_id``.

        The highest fully-contiguous broker ID is returned separately as
        ``cursor_candidate``; this port never advances any durable
        cursor, so a failed consumer re-fetches the identical window.
        """
        since = _validate_id(since_id, field="since_id")
        _validate_page_size(page_size)
        response = self._client.request(
            "GET",
            self._client.account_path("/transactions/sinceid"),
            params={"id": since_id},
        )
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(
            body.get("transactions"), list
        ):
            raise TransactionOperationError(
                "protocol_error", "since response is not JSON"
            )
        rows, duplicates = _collect_rows(body["transactions"], duplicates=0)
        return _normalize(
            rows,
            duplicates=duplicates,
            expected_start=since + 1,
            declared_from=None,
            declared_to=None,
            request_id=request_id or f"since-{since_id}",
        )

    # ------------------------------------------------------------------
    # Internal pagination over the ID-range endpoint
    # ------------------------------------------------------------------

    def _fetch_idrange(
        self,
        from_id: str,
        to_id: str,
        *,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        response = self._client.request(
            "GET",
            self._client.account_path("/transactions/idrange"),
            params={
                "from": from_id,
                "to": to_id,
                "pageSize": page_size,
            },
        )
        pages = 0
        all_rows: list[dict[str, Any]] = []
        duplicates = 0
        while True:
            pages += 1
            if pages > MAX_PAGES:
                raise TransactionOperationError(
                    "pagination_limit_exceeded",
                    f"range {from_id}-{to_id} exceeded {MAX_PAGES} pages",
                )
            body = response.json_body
            if not isinstance(body, dict) or not isinstance(
                body.get("transactions"), list
            ):
                raise TransactionOperationError(
                    "protocol_error", "idrange response is not JSON"
                )
            page_rows, page_duplicates = _collect_rows(
                body["transactions"], duplicates=0
            )
            all_rows.extend(page_rows)
            duplicates += page_duplicates
            next_pages = body.get("pages")
            if not isinstance(next_pages, list) or not next_pages:
                return all_rows, duplicates
            page_url = next_pages[0]
            if not isinstance(page_url, str):
                raise TransactionOperationError(
                    "protocol_error", "page URL is not a string"
                )
            response = self._client.request(
                "GET", _path_from_page_url(page_url)
            )


def _validate_id(value: str, *, field: str) -> int:
    if not value.strip():
        raise TransactionOperationError("invalid_request_id", f"{field} is empty")
    if not value.isdigit():
        # Local timestamps and other non-ID cursors are rejected outright.
        raise TransactionOperationError(
            "invalid_cursor", f"{field} must be a digit broker transaction ID"
        )
    return int(value)


def _validate_page_size(page_size: int) -> None:
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise TransactionOperationError(
            "invalid_page_size", f"page_size must be in 1..{MAX_PAGE_SIZE}"
        )


def _collect_rows(
    rows: list[Any], *, duplicates: int
) -> tuple[list[dict[str, Any]], int]:
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    dup_count = duplicates
    for row in rows:
        if not isinstance(row, dict):
            raise TransactionOperationError(
                "protocol_error", "transaction row is not an object"
            )
        transaction_id = str(row.get("id", "")).strip()
        if not transaction_id.isdigit():
            raise TransactionOperationError(
                "protocol_error", "transaction row id is not a digit string"
            )
        if transaction_id in seen:
            dup_count += 1
            continue
        seen.add(transaction_id)
        collected.append(row)
    return collected, dup_count


def _normalize(
    rows: list[dict[str, Any]],
    *,
    duplicates: int,
    expected_start: int,
    declared_from: str | None,
    declared_to: str | None,
    request_id: str,
) -> TransactionRangeResult:
    # Broker-ID ordering: out-of-order rows sort deterministically.
    ordered = sorted(rows, key=lambda row: int(str(row["id"])))
    transactions = tuple(
        _transaction_from_row(row, request_id=request_id) for row in ordered
    )
    ids = [int(transaction.transaction_id) for transaction in transactions]
    declared_to_int = int(declared_to) if declared_to is not None else None
    gaps, candidate = _gaps_and_candidate(
        ids,
        expected_start=expected_start,
        declared_to=declared_to_int,
    )
    return TransactionRangeResult(
        transactions=transactions,
        declared_from=declared_from,
        declared_to=declared_to,
        cursor_candidate=str(candidate) if candidate is not None else None,
        gaps=tuple(gaps),
        duplicate_count=duplicates,
        request_id=request_id,
    )


def _gaps_and_candidate(
    ids: list[int],
    *,
    expected_start: int,
    declared_to: int | None,
) -> tuple[list[TransactionGap], int | None]:
    """Return missing-ID spans and the highest fully-contiguous prefix ID.

    The prefix is only contiguous from ``expected_start``; once a hole is
    found the candidate is sealed and never advances past it.
    """
    gaps: list[TransactionGap] = []
    expected = expected_start
    candidate: int | None = None
    sealed = False
    for transaction_id in ids:
        if transaction_id == expected:
            if not sealed:
                candidate = transaction_id
            expected = transaction_id + 1
            continue
        # transaction_id > expected: an explicit missing span.
        sealed = True
        gaps.append(
            TransactionGap(
                gap_from=str(expected), gap_to=str(transaction_id - 1)
            )
        )
        expected = transaction_id + 1
    if declared_to is not None and expected <= declared_to:
        gaps.append(
            TransactionGap(gap_from=str(expected), gap_to=str(declared_to))
        )
    return gaps, candidate


def _transaction_from_row(row: dict[str, Any], *, request_id: str) -> TransactionResult:
    return TransactionResult(
        transaction_id=str(row["id"]),
        transaction_type=str(row.get("type", "")).strip(),
        time=_parse_time(row.get("time")),
        instrument=_optional_str(row.get("instrument")),
        units=_optional_decimal(row.get("units")),
        price=_optional_decimal(row.get("price")),
        realized_pl=_optional_decimal(row.get("pl")),
        financing=_optional_decimal(row.get("financing")),
        request_id=request_id,
    )


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _path_from_page_url(url: str) -> str:
    marker = "/v3/accounts/"
    index = url.find(marker)
    if index < 0:
        raise TransactionOperationError(
            "protocol_error", "page URL is not an account API path"
        )
    return url[index:]


def _path(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "TransactionGap",
    "TransactionOperationError",
    "TransactionOpsClient",
    "TransactionRangeResult",
    "TransactionResult",
]
