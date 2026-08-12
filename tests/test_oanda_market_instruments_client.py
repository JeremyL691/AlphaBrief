"""M04-W02: OANDA instruments client and strict parsing.

Covers:
- every response row becomes exactly one strict metadata object
  preserving name, displayName, raw type, precisions, sizes, margin,
  pipLocation, and stop-distance fields (AC-M04-W02-01);
- unknown fields are retained in a versioned raw payload while missing
  or invalid required trading fields reject the whole candidate snapshot
  without partial publication (AC-M04-W02-02);
- parsing uses Decimal-safe values and never infers precision or size
  from symbol naming (AC-M04-W02-03).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentParseError,
    fetch_instruments,
    parse_instruments_response,
)

ACCOUNT_ID = "101-004-1234567-001"


def _instrument_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": "EUR_USD",
        "type": "CURRENCY",
        "displayName": "EUR/USD",
        "pipLocation": -4,
        "displayPrecision": 5,
        "tradeUnitsPrecision": 0,
        "minimumTradeSize": "1",
        "maximumTrailingStopDistance": "100.0",
        "minimumTrailingStopDistance": "0.050",
        "maximumPositionSize": "0",
        "maximumOrderUnits": "0",
        "marginRate": "0.05",
        "guaranteedStopLossOrderMode": "DISABLED",
    }
    row.update(overrides)
    return row


def _body(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"instruments": list(rows)}


def _http_send(body: dict[str, Any]) -> Any:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        return json.dumps(body).encode("utf-8")

    return _send


# ---------------------------------------------------------------------------
# AC-M04-W02-01: strict per-row metadata
# ---------------------------------------------------------------------------


def test_every_row_becomes_exactly_one_metadata_object() -> None:
    snapshot = parse_instruments_response(
        _body(
            _instrument_row(),
            _instrument_row(name="XAU_USD", type="METAL", displayName="Gold"),
        ),
        account_id=ACCOUNT_ID,
    )
    assert len(snapshot.instruments) == 2
    eur = snapshot.instruments[0]
    assert eur.name == "EUR_USD"
    assert eur.display_name == "EUR/USD"
    assert eur.raw_type == "CURRENCY"
    assert eur.display_precision == 5
    assert eur.trade_units_precision == 0
    assert eur.minimum_trade_size == Decimal("1")
    assert eur.maximum_order_units == Decimal("0")
    assert eur.maximum_position_size == Decimal("0")
    assert eur.margin_rate == Decimal("0.05")
    assert eur.pip_location == -4
    assert eur.minimum_trailing_stop_distance == Decimal("0.050")
    assert eur.maximum_trailing_stop_distance == Decimal("100.0")
    assert snapshot.account_id_hash != ACCOUNT_ID


def test_fetch_instruments_uses_account_scoped_endpoint() -> None:
    captured: dict[str, Any] = {}

    def _send(request: Request, timeout_seconds: float) -> bytes:
        captured["path"] = request.full_url
        return json.dumps(_body(_instrument_row())).encode("utf-8")

    client = OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token="t",
        account_id=ACCOUNT_ID,
    )
    snapshot = fetch_instruments(client, account_id=ACCOUNT_ID)
    assert len(snapshot.instruments) == 1
    assert f"/v3/accounts/{ACCOUNT_ID}/instruments" in captured["path"]


# ---------------------------------------------------------------------------
# AC-M04-W02-02: raw payload retention and whole-snapshot rejection
# ---------------------------------------------------------------------------


def test_unknown_fields_are_retained_in_versioned_raw_payload() -> None:
    snapshot = parse_instruments_response(
        _body(_instrument_row(futureField="future-value")),
        account_id=ACCOUNT_ID,
    )
    instrument = snapshot.instruments[0]
    assert instrument.raw_payload["futureField"] == "future-value"
    assert instrument.raw_payload["name"] == "EUR_USD"
    assert snapshot.raw_payload_version == "oanda-v20-1"


def test_missing_required_field_rejects_whole_snapshot() -> None:
    with pytest.raises(InstrumentParseError, match="marginRate"):
        parse_instruments_response(
            _body(_instrument_row(), _instrument_row(marginRate=None)),
            account_id=ACCOUNT_ID,
        )


def test_invalid_precision_rejects_whole_snapshot() -> None:
    with pytest.raises(InstrumentParseError):
        parse_instruments_response(
            _body(_instrument_row(displayPrecision="not-an-int")),
            account_id=ACCOUNT_ID,
        )


def test_malformed_response_rejects() -> None:
    with pytest.raises(InstrumentParseError):
        parse_instruments_response({"nope": True}, account_id=ACCOUNT_ID)
    with pytest.raises(InstrumentParseError):
        parse_instruments_response({"instruments": []}, account_id=ACCOUNT_ID)


# ---------------------------------------------------------------------------
# AC-M04-W02-03: Decimal-safe, never inferred from symbol naming
# ---------------------------------------------------------------------------


def test_numeric_fields_are_decimal_safe() -> None:
    snapshot = parse_instruments_response(
        _body(_instrument_row()),
        account_id=ACCOUNT_ID,
    )
    instrument = snapshot.instruments[0]
    assert isinstance(instrument.minimum_trade_size, Decimal)
    assert isinstance(instrument.margin_rate, Decimal)
    assert isinstance(instrument.minimum_trailing_stop_distance, Decimal)
    assert isinstance(instrument.maximum_trailing_stop_distance, Decimal)
    # JSON serialization preserves the values.
    payload = json.loads(snapshot.model_dump_json())
    assert payload["instruments"][0]["minimum_trade_size"] == "1"


def test_float_values_are_rejected() -> None:
    with pytest.raises(InstrumentParseError):
        parse_instruments_response(
            _body(_instrument_row(minimumTradeSize=1.5)),
            account_id=ACCOUNT_ID,
        )


def test_metadata_never_inferred_from_symbol_naming() -> None:
    """A symbol with a dot or hyphen still carries its own explicit fields."""
    snapshot = parse_instruments_response(
        _body(_instrument_row(name="XPT_USD", type="METAL")),
        account_id=ACCOUNT_ID,
    )
    instrument = snapshot.instruments[0]
    # Precision and size come from the response row, not the symbol text.
    assert instrument.display_precision == 5
    assert instrument.minimum_trade_size == Decimal("1")
    assert instrument.raw_type == "METAL"
