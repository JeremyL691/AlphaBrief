"""M06-W04: trade and position lifecycle operations.

Covers:
- trade/position get, list, partial close, full close, side-specific
  close, and protective dependent orders match exact request and response
  fixtures (AC-M06-W04-01);
- partial-close units, ALL semantics, long/short side handling, realized
  PnL, financing, and related transaction IDs stay distinct and
  Decimal-safe (AC-M06-W04-02);
- missing, stale, already closed, account-mismatched, over-close, and
  unsupported requests fail closed without a local synthetic position
  mutation (AC-M06-W04-03).
"""

from __future__ import annotations

import json
from decimal import Decimal
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.account_ops import AccountOpsClient
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.position_ops import (
    PositionOperationError,
    PositionOpsClient,
)
from alphabrief_execution.broker.oanda.trade_ops import (
    TradeOperationError,
    TradeOpsClient,
)

ACCOUNT_ID = "101-004-1234567-001"

TRADE_OPEN_TIME = "2026-08-04T12:00:00.000000000Z"


def _instrument() -> InstrumentMetadata:
    return InstrumentMetadata(
        name="EUR_USD",
        display_name="EUR/USD",
        raw_type="CURRENCY",
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
        raw_payload={"guaranteedStopLossOrderMode": "DISABLED"},
    )


def _gslo_enabled_instrument() -> InstrumentMetadata:
    return _instrument().model_copy(
        update={"raw_payload": {"guaranteedStopLossOrderMode": "ENABLED"}}
    )


class _FakeBroker:
    """A deterministic in-memory OANDA trade/position store."""

    def __init__(self) -> None:
        self.trades: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.next_id = 1000
        self.race_close = False

    def open_trade(
        self,
        trade_id: str,
        instrument: str,
        units: str,
        *,
        price: str = "1.10500",
        client_order_id: str | None = None,
    ) -> None:
        trade: dict[str, Any] = {
            "id": trade_id,
            "instrument": instrument,
            "price": price,
            "openTime": TRADE_OPEN_TIME,
            "state": "OPEN",
            "initialUnits": units,
            "currentUnits": units,
            "realizedPL": "0",
            "unrealizedPL": "2.50",
            "financing": "0",
        }
        if client_order_id is not None:
            trade["clientExtensions"] = {"id": client_order_id}
        self.trades[trade_id] = trade
        self._sync_position(instrument)

    def set_position(
        self,
        instrument: str,
        *,
        long_units: str = "0",
        short_units: str = "0",
    ) -> None:
        self.positions[instrument] = {
            "instrument": instrument,
            "long": {
                "units": long_units,
                "averagePrice": "1.10500" if long_units != "0" else "0",
                "pl": "3.25" if long_units != "0" else "0",
                "unrealizedPL": "1.10" if long_units != "0" else "0",
            },
            "short": {
                "units": short_units,
                "averagePrice": "1.10200" if short_units != "0" else "0",
                "pl": "-1.50" if short_units != "0" else "0",
                "unrealizedPL": "0.75" if short_units != "0" else "0",
            },
        }

    def _sync_position(self, instrument: str) -> None:
        long_total = Decimal("0")
        short_total = Decimal("0")
        for trade in self.trades.values():
            if trade["instrument"] != instrument or trade["state"] != "OPEN":
                continue
            units = Decimal(str(trade["currentUnits"]))
            if units > 0:
                long_total += units
            else:
                short_total += abs(units)
        self.set_position(
            instrument,
            long_units=str(long_total),
            short_units=str(short_total),
        )

    def _next_transaction_id(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def close_trade(self, trade_id: str, body: dict[str, Any]) -> dict[str, Any]:
        trade = self.trades.get(trade_id)
        if trade is None:
            raise KeyError(trade_id)
        if self.race_close or trade["state"] != "OPEN":
            # The trade closed between the port's read and its close
            # request: OANDA answers with a cancel, never a fill.
            return {
                "orderCreateTransaction": {"id": self._next_transaction_id()},
                "orderFillTransaction": None,
                "orderCancelTransaction": {"id": self._next_transaction_id()},
                "tradeCloseTransaction": None,
            }
        open_units = Decimal(str(trade["currentUnits"]))
        if "units" in body:
            requested = Decimal(str(body["units"]))
            closed = min(requested, abs(open_units))
        else:
            closed = abs(open_units)
        remaining = abs(open_units) - closed
        trade["currentUnits"] = str(
            Decimal(str(trade["currentUnits"])) - closed if open_units > 0 else closed
        )
        trade["realizedPL"] = "12.34"
        trade["financing"] = "-0.05"
        if remaining == 0:
            trade["state"] = "CLOSED"
            trade["closeTime"] = "2026-08-05T09:00:00.000000000Z"
        self._sync_position(trade["instrument"])
        return {
            "orderCreateTransaction": {
                "id": self._next_transaction_id(),
                "time": "2026-08-05T09:00:00.000000000Z",
            },
            "orderFillTransaction": {
                "id": self._next_transaction_id(),
                "time": "2026-08-05T09:00:00.000000000Z",
                "units": str(closed),
            },
            "tradeCloseTransaction": {
                "id": self._next_transaction_id(),
                "time": "2026-08-05T09:00:00.000000000Z",
            },
            "realizedPL": "12.34",
            "financing": "-0.05",
        }

    def add_dependent(
        self, trade_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        trade = self.trades.get(trade_id)
        if trade is None:
            raise KeyError(trade_id)
        if trade["state"] != "OPEN":
            raise HTTPError("", 422, "trade not open", Message(), None)
        kind = next(iter(body.keys()))
        type_name = {
            "takeProfit": "TAKE_PROFIT_ORDER",
            "stopLoss": "STOP_LOSS_ORDER",
            "trailingStopLoss": "TRAILING_STOP_LOSS_ORDER",
            "guaranteedStopLoss": "GUARANTEED_STOP_LOSS_ORDER",
        }[kind]
        order_id = self._next_transaction_id()
        self.orders[order_id] = {
            "id": order_id,
            "type": type_name,
            "instrument": trade["instrument"],
            "tradeID": trade_id,
            "state": "PENDING",
        }
        return {
            "orderCreateTransaction": {
                "id": order_id,
                "type": type_name,
                "time": "2026-08-05T09:00:00.000000000Z",
            },
            "orderFillTransaction": None,
        }

    def close_position(
        self, instrument: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        position = self.positions.get(instrument)
        if position is None:
            raise KeyError(instrument)
        result: dict[str, Any] = {}
        for side in ("long", "short"):
            key = f"{side}Units"
            # OANDA semantics: an omitted side defaults to ALL; "NONE"
            # leaves the side untouched.
            if key not in body or body[key] == "NONE":
                continue
            if body[key] == "ALL":
                closed = Decimal(str(position[side]["units"]))
            else:
                closed = min(
                    Decimal(str(body[key])), Decimal(str(position[side]["units"]))
                )
            side_data = position[side]
            open_units = Decimal(str(side_data["units"]))
            side_data["units"] = str(open_units - closed)
            result[f"{side}OrderCreateTransaction"] = {
                "id": self._next_transaction_id()
            }
            result[f"{side}OrderFillTransaction"] = {
                "id": self._next_transaction_id(),
                "units": str(closed),
            }
            result[f"{side}OrderCancelTransaction"] = None
        return result


def _send_factory(broker: _FakeBroker, captured: list[dict[str, Any]]) -> Any:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        method = request.method
        url = request.full_url
        raw = request.data
        body = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else {}
        captured.append({"method": method, "url": url, "body": body})
        path = url.split(f"/v3/accounts/{ACCOUNT_ID}", 1)[1]
        path, _, query = path.partition("?")

        if method == "GET" and path == "/trades":
            ordered: list[dict[str, Any]] = [
                broker.trades[tid]
                for tid in sorted(broker.trades, key=lambda t: int(t))
            ]
            return json.dumps({"trades": ordered}).encode("utf-8")
        if method == "GET" and path.startswith("/trades/"):
            trade_id = path.split("/trades/", 1)[1]
            found = broker.trades.get(trade_id)
            if found is None:
                raise HTTPError(url, 404, "not found", Message(), None)
            return json.dumps({"trade": found}).encode("utf-8")
        if method == "PUT" and path.endswith("/close") and "/trades/" in path:
            trade_id = path.split("/trades/", 1)[1].split("/", 1)[0]
            try:
                return json.dumps(broker.close_trade(trade_id, body)).encode("utf-8")
            except KeyError:
                raise HTTPError(url, 404, "not found", Message(), None) from None
        if method == "PUT" and "/trades/" in path and path.endswith("/orders"):
            trade_id = path.split("/trades/", 1)[1].split("/", 1)[0]
            return json.dumps(broker.add_dependent(trade_id, body)).encode("utf-8")
        if method == "GET" and path == "/positions":
            ordered_positions: list[dict[str, Any]] = [
                broker.positions[instrument]
                for instrument in sorted(broker.positions)
            ]
            return json.dumps({"positions": ordered_positions}).encode("utf-8")
        if method == "GET" and path.startswith("/positions/"):
            instrument = path.split("/positions/", 1)[1]
            found = broker.positions.get(instrument)
            if found is None:
                raise HTTPError(url, 404, "not found", Message(), None)
            return json.dumps({"position": found}).encode("utf-8")
        if (
            method == "PUT"
            and path.startswith("/positions/")
            and path.endswith("/close")
        ):
            instrument = path.split("/positions/", 1)[1].split("/", 1)[0]
            try:
                return json.dumps(broker.close_position(instrument, body)).encode(
                    "utf-8"
                )
            except KeyError:
                raise HTTPError(url, 404, "not found", Message(), None) from None
        if method == "GET" and path == "/summary":
            return json.dumps(
                {
                    "account": {
                        "id": ACCOUNT_ID,
                        "currency": "USD",
                        "balance": "100000.00",
                        "NAV": "100050.00",
                        "unrealizedPL": "50.00",
                        "marginUsed": "1000.00",
                        "marginAvailable": "99000.00",
                        "openOrderCount": 1,
                        "openTradeCount": 2,
                        "openPositionCount": 1,
                        "lastTransactionID": "2047",
                    }
                }
            ).encode("utf-8")
        if method == "GET" and path == "/changes":
            return json.dumps(
                {
                    "changes": {
                        "ordersCreated": [],
                        "ordersCancelled": [],
                        "ordersFilled": [{"id": "2010"}],
                        "ordersTriggered": [],
                        "tradesOpened": [{"id": "2011"}],
                        "tradesReduced": [],
                        "tradesClosed": [{"id": "2012"}],
                        "positionsClosed": [],
                        "positionsReduced": [],
                        "transactions": [
                            {"id": "2010", "type": "ORDER_FILL"},
                            {"id": "2011", "type": "ORDER_FILL"},
                            {"id": "2012", "type": "TRADE_CLOSE"},
                        ],
                    },
                    "state": {
                        "account": {
                            "balance": "100012.29",
                            "NAV": "100055.00",
                            "unrealizedPL": "42.71",
                        }
                    },
                    "lastTransactionID": "2047",
                }
            ).encode("utf-8")
        raise HTTPError(url, 405, "method not allowed", Message(), None)

    return _send


def _http_client(
    broker: _FakeBroker, captured: list[dict[str, Any]]
) -> OandaHttpClient:
    return OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send_factory(broker, captured),
        token="t",
        account_id=ACCOUNT_ID,
    )


def _clients(
    broker: _FakeBroker,
) -> tuple[TradeOpsClient, PositionOpsClient, AccountOpsClient, list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []
    http = _http_client(broker, captured)
    return (
        TradeOpsClient(http),
        PositionOpsClient(http),
        AccountOpsClient(http),
        captured,
    )


# ---------------------------------------------------------------------------
# AC-M06-W04-01: get, list, partial/full close, side-specific close,
# protective dependents, summary, and changes match exact fixtures
# ---------------------------------------------------------------------------


def test_trade_get_and_list_flow() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000", client_order_id="client-1")
    broker.open_trade("2", "EUR_USD", "-500")
    trades, _, _, _ = _clients(broker)
    state = trades.get_trade("1")
    assert state.broker_trade_id == "1"
    assert state.client_order_id == "client-1"
    assert state.instrument == "EUR_USD"
    assert state.state == "OPEN"
    assert state.current_units == Decimal("1000")
    assert state.unrealized_pl == Decimal("2.50")
    listing = trades.list_trades(page=1, page_size=1)
    assert listing.page == 1
    assert listing.has_more is True
    assert len(listing.trades) == 1
    assert listing.trades[0].broker_trade_id == "1"
    page_two = trades.list_trades(page=2, page_size=1)
    assert page_two.has_more is False
    assert page_two.trades[0].current_units == Decimal("-500")


def test_trade_full_close_all_semantics() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, _ = _clients(broker)
    result = trades.close_trade("1")
    assert result.broker_trade_id == "1"
    assert result.closed_units == Decimal("1000")
    assert result.realized_pl == Decimal("12.34")
    assert result.financing == Decimal("-0.05")
    # Related transaction IDs stay distinct.
    assert (
        result.order_create_transaction_id
        != result.order_fill_transaction_id
        != result.trade_close_transaction_id
    )
    assert broker.trades["1"]["state"] == "CLOSED"


def test_trade_partial_close_units() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, _ = _clients(broker)
    result = trades.close_trade("1", units=Decimal("400"))
    assert result.closed_units == Decimal("400")
    assert result.realized_pl == Decimal("12.34")
    # The trade stays open with the remaining units.
    remaining = trades.get_trade("1")
    assert remaining.state == "OPEN"
    assert remaining.current_units == Decimal("600")


def test_position_get_and_list_flow() -> None:
    broker = _FakeBroker()
    broker.set_position("EUR_USD", long_units="1000", short_units="250")
    broker.set_position("USD_JPY", long_units="0", short_units="0")
    _, positions, _, _ = _clients(broker)
    state = positions.get_position("EUR_USD")
    assert state.instrument == "EUR_USD"
    assert state.side == "BOTH"
    assert state.long_units == Decimal("1000")
    assert state.short_units == Decimal("250")
    assert state.long_average_price == Decimal("1.10500")
    assert state.long_pl == Decimal("3.25")
    assert state.short_unrealized_pl == Decimal("0.75")
    flat = positions.get_position("USD_JPY")
    assert flat.side == "NONE"
    listing = positions.list_positions()
    assert {p.instrument for p in listing.positions} == {"EUR_USD", "USD_JPY"}


def test_position_close_long_side_all() -> None:
    broker = _FakeBroker()
    broker.set_position("EUR_USD", long_units="1000", short_units="0")
    _, positions, _, _ = _clients(broker)
    result = positions.close_position(
        "EUR_USD", long_units="ALL", short_units="NONE"
    )
    assert result.long_closed_units == Decimal("1000")
    assert result.long_order_fill_transaction_id is not None
    assert (
        result.long_order_create_transaction_id
        != result.long_order_fill_transaction_id
    )
    assert result.short_closed_units == Decimal("0")
    assert result.short_order_create_transaction_id is None
    # The broker-side long units are gone: no local synthetic mutation.
    after = positions.get_position("EUR_USD")
    assert after.long_units == Decimal("0")
    assert after.side == "NONE"


def test_position_close_both_sides() -> None:
    broker = _FakeBroker()
    broker.set_position("EUR_USD", long_units="1000", short_units="250")
    _, positions, _, _ = _clients(broker)
    result = positions.close_position(
        "EUR_USD", long_units=Decimal("400"), short_units=Decimal("250")
    )
    assert result.long_closed_units == Decimal("400")
    assert result.short_closed_units == Decimal("250")
    # Both sides carry distinct transaction IDs.
    assert (
        result.long_order_create_transaction_id
        != result.short_order_create_transaction_id
    )
    after = positions.get_position("EUR_USD")
    assert after.long_units == Decimal("600")
    assert after.short_units == Decimal("0")
    assert after.side == "LONG"


def test_trade_dependent_take_profit_and_stop_loss() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, _ = _clients(broker)
    tp = trades.add_trade_dependent(
        "1", _instrument(), take_profit_price=Decimal("1.11000")
    )
    assert tp.broker_trade_id == "1"
    assert tp.dependent_type == "TAKE_PROFIT_ORDER"
    sl = trades.add_trade_dependent(
        "1", _instrument(), stop_loss_price=Decimal("1.10000")
    )
    assert sl.dependent_type == "STOP_LOSS_ORDER"
    assert tp.dependent_order_id != sl.dependent_order_id


def test_trade_dependent_trailing_stop_distance() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, _ = _clients(broker)
    result = trades.add_trade_dependent(
        "1", _instrument(), trailing_stop_distance=Decimal("0.00200")
    )
    assert result.dependent_type == "TRAILING_STOP_LOSS_ORDER"


def test_account_summary_matches_fixture() -> None:
    broker = _FakeBroker()
    _, _, accounts, _ = _clients(broker)
    summary = accounts.account_summary()
    assert summary.account_id == ACCOUNT_ID
    assert summary.currency == "USD"
    assert summary.balance == Decimal("100000.00")
    assert summary.nav == Decimal("100050.00")
    assert summary.unrealized_pl == Decimal("50.00")
    assert summary.margin_used == Decimal("1000.00")
    assert summary.margin_available == Decimal("99000.00")
    assert summary.open_order_count == 1
    assert summary.open_trade_count == 2
    assert summary.open_position_count == 1
    assert summary.last_transaction_id == "2047"


def test_account_changes_matches_fixture() -> None:
    broker = _FakeBroker()
    _, _, accounts, _ = _clients(broker)
    changes = accounts.account_changes("2000")
    assert changes.since_transaction_id == "2000"
    assert changes.last_transaction_id == "2047"
    assert changes.orders_filled == 1
    assert changes.trades_opened == 1
    assert changes.trades_closed == 1
    assert changes.orders_created == 0
    assert changes.transactions == 3
    assert changes.balance == Decimal("100012.29")
    assert changes.nav == Decimal("100055.00")
    assert changes.unrealized_pl == Decimal("42.71")


# ---------------------------------------------------------------------------
# AC-M06-W04-03: fail-closed without local synthetic mutation
# ---------------------------------------------------------------------------


def test_unknown_trade_fails_closed() -> None:
    broker = _FakeBroker()
    trades, _, _, _ = _clients(broker)
    with pytest.raises(TradeOperationError) as excinfo:
        trades.get_trade("9999")
    assert excinfo.value.kind == "unknown_trade"
    with pytest.raises(TradeOperationError) as excinfo:
        trades.close_trade("9999")
    assert excinfo.value.kind == "unknown_trade"


def test_already_closed_trade_fails_closed() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    broker.trades["1"]["state"] = "CLOSED"
    trades, _, _, _ = _clients(broker)
    with pytest.raises(TradeOperationError) as excinfo:
        trades.close_trade("1")
    assert excinfo.value.kind == "trade_state_invalid"
    with pytest.raises(TradeOperationError) as excinfo:
        trades.add_trade_dependent(
            "1", _instrument(), take_profit_price=Decimal("1.11000")
        )
    assert excinfo.value.kind == "trade_state_invalid"


def test_negative_units_fail_closed() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, captured = _clients(broker)
    with pytest.raises(TradeOperationError) as excinfo:
        trades.close_trade("1", units=Decimal("-100"))
    assert excinfo.value.kind == "invalid_units"
    assert broker.trades["1"]["state"] == "OPEN"
    # Only the pre-close read reached the broker, never a close request.
    assert [c["method"] for c in captured] == ["GET"]


def test_over_close_trade_fails_closed() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, captured = _clients(broker)
    with pytest.raises(TradeOperationError) as excinfo:
        trades.close_trade("1", units=Decimal("1500"))
    assert excinfo.value.kind == "over_close"
    # No close request reached the broker and no local mutation happened.
    assert [c["method"] for c in captured] == ["GET"]
    assert broker.trades["1"]["currentUnits"] == "1000"


def test_stale_close_race_fails_closed() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, _ = _clients(broker)
    # The trade closes between the port's read and its close request:
    # the broker answers with a cancel transaction and no fill.
    broker.race_close = True
    with pytest.raises(TradeOperationError) as excinfo:
        trades.close_trade("1")
    assert excinfo.value.kind == "trade_state_invalid"
    # The local broker state was never mutated by the failed close.
    assert broker.trades["1"]["state"] == "OPEN"


def test_unknown_position_fails_closed() -> None:
    broker = _FakeBroker()
    _, positions, _, _ = _clients(broker)
    with pytest.raises(PositionOperationError) as excinfo:
        positions.get_position("GBP_JPY")
    assert excinfo.value.kind == "unknown_position"
    with pytest.raises(PositionOperationError) as excinfo:
        positions.close_position("GBP_JPY", long_units="ALL", short_units="NONE")
    assert excinfo.value.kind == "unknown_position"


def test_position_close_requires_side_fails_closed() -> None:
    broker = _FakeBroker()
    broker.set_position("EUR_USD", long_units="1000")
    _, positions, _, captured = _clients(broker)
    with pytest.raises(PositionOperationError) as excinfo:
        positions.close_position("EUR_USD")
    assert excinfo.value.kind == "invalid_units"
    assert captured == []


def test_position_over_close_fails_closed() -> None:
    broker = _FakeBroker()
    broker.set_position("EUR_USD", long_units="1000", short_units="0")
    _, positions, _, captured = _clients(broker)
    with pytest.raises(PositionOperationError) as excinfo:
        positions.close_position("EUR_USD", short_units=Decimal("500"))
    assert excinfo.value.kind == "over_close"
    # Only the pre-close read reached the broker, never a close request.
    assert [c["method"] for c in captured] == ["GET"]


def test_unsupported_guaranteed_stop_fails_closed() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, _ = _clients(broker)
    with pytest.raises(TradeOperationError) as excinfo:
        trades.add_trade_dependent(
            "1", _instrument(), guaranteed_stop_price=Decimal("1.09000")
        )
    assert excinfo.value.kind == "unsupported_dependent"
    # The same request is accepted when the instrument enables GSLO.
    result = trades.add_trade_dependent(
        "1",
        _gslo_enabled_instrument(),
        guaranteed_stop_price=Decimal("1.09000"),
    )
    assert result.dependent_type == "GUARANTEED_STOP_LOSS_ORDER"


def test_multiple_dependent_kinds_fail_closed() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, _, _, captured = _clients(broker)
    with pytest.raises(TradeOperationError) as excinfo:
        trades.add_trade_dependent(
            "1",
            _instrument(),
            take_profit_price=Decimal("1.11000"),
            stop_loss_price=Decimal("1.10000"),
        )
    assert excinfo.value.kind == "invalid_dependent"
    # Only the pre-close read reached the broker, never a write.
    assert [c["method"] for c in captured] == ["GET"]


def test_every_response_carries_request_correlation() -> None:
    broker = _FakeBroker()
    broker.open_trade("1", "EUR_USD", "1000")
    trades, positions, accounts, _ = _clients(broker)
    assert trades.get_trade("1", request_id="manual-t").request_id == "manual-t"
    assert trades.list_trades(request_id="manual-l").request_id == "manual-l"
    closed = trades.close_trade("1", request_id="manual-c")
    assert closed.request_id == "manual-c"
    assert positions.get_position("EUR_USD", request_id="manual-p").request_id == (
        "manual-p"
    )
    assert positions.list_positions(request_id="manual-pl").request_id == "manual-pl"
    assert accounts.account_summary(request_id="manual-s").request_id == "manual-s"
    assert accounts.account_changes("2000", request_id="manual-ch").request_id == (
        "manual-ch"
    )
