"""M04-W02: instrument metadata strictness (AC-M04-W02-01/03).

The metadata model is frozen and rejects unknown top-level fields, every
numeric field is Decimal, and no field is derived from the symbol name.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from pydantic import ValidationError


def _metadata(**overrides: object) -> InstrumentMetadata:
    payload: dict[str, object] = {
        "name": "US30_USD",
        "display_name": "US Wall St 30",
        "raw_type": "CFD",
        "display_precision": 1,
        "trade_units_precision": 0,
        "minimum_trade_size": Decimal("1"),
        "maximum_order_units": Decimal("0"),
        "maximum_position_size": Decimal("0"),
        "margin_rate": Decimal("0.02"),
        "pip_location": 1,
    }
    payload.update(overrides)
    return InstrumentMetadata.model_validate(payload)


def test_metadata_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _metadata(symbol_precision=3)


def test_metadata_rejects_float_money_and_sizes() -> None:
    with pytest.raises(ValidationError, match="must not be floats"):
        _metadata(minimum_trade_size=1.5)
    with pytest.raises(ValidationError, match="must not be floats"):
        _metadata(margin_rate=0.05)


def test_precision_fields_are_ints_only() -> None:
    with pytest.raises(ValidationError):
        _metadata(display_precision="1.5")
    assert _metadata(display_precision="2").display_precision == 2


def test_margin_rate_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _metadata(margin_rate=Decimal("0"))


def test_stop_distances_are_optional_decimals() -> None:
    meta = _metadata()
    assert meta.minimum_trailing_stop_distance is None
    assert meta.maximum_trailing_stop_distance is None
    meta = _metadata(
        minimum_trailing_stop_distance=Decimal("0.050"),
        maximum_trailing_stop_distance=Decimal("100.0"),
    )
    assert meta.minimum_trailing_stop_distance == Decimal("0.050")


def test_raw_payload_is_immutable_copy() -> None:
    meta = _metadata(raw_payload={"future": "x"})
    assert meta.raw_payload == {"future": "x"}
