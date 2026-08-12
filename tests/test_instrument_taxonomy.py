"""M04-W04: deterministic instrument taxonomy.

Covers:
- fixtures cover Currency, Metal, index/commodity/bond/equity CFDs when
  returned, and unknown values with deterministic category and
  taxonomy-version output (AC-M04-W04-01);
- unrecognized broker types or display patterns remain visible as
  unknown with their raw value and never disappear from catalog counts
  or search (AC-M04-W04-02);
- taxonomy changes create a new derived version and cannot mutate the
  raw instrument snapshot (AC-M04-W04-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentCatalogSnapshot,
    InstrumentMetadata,
    parse_instruments_response,
)
from alphabrief_execution.broker.oanda.taxonomy import (
    TAXONOMY_VERSION,
    ClassifiedInstrument,
    classify_instrument,
    classify_snapshot,
)


def _instrument(name: str, raw_type: str, display: str) -> InstrumentMetadata:
    return InstrumentMetadata(
        name=name,
        display_name=display,
        raw_type=raw_type,
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
    )


def _snapshot(*instruments: InstrumentMetadata) -> InstrumentCatalogSnapshot:
    return InstrumentCatalogSnapshot(
        account_id_hash="acct-hash",
        fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
        instruments=instruments,
    )


# ---------------------------------------------------------------------------
# AC-M04-W04-01: deterministic category fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "raw_type", "display", "category"),
    [
        ("EUR_USD", "CURRENCY", "EUR/USD", "CURRENCY"),
        ("XAU_USD", "METAL", "Gold", "METAL"),
        ("US30_USD", "CFD", "US Wall St 30", "INDEX_CFD"),
        ("SPX500_USD", "CFD", "US SPX 500", "INDEX_CFD"),
        ("US_OIL", "CFD", "US Oil", "COMMODITY_CFD"),
        ("US10Y", "CFD", "US 10YR T-Note", "BOND_CFD"),
        ("AAPL_USD", "CFD", "Apple Inc", "EQUITY_CFD"),
        ("XBT_USD", "CFD", "Bitcoin", "CRYPTO_CFD"),
        ("MYSTERY", "CFD", "Mystery Instrument 3000", "OTHER_CFD"),
        ("UNK", "FUTURE", "Some Future", "OTHER_CFD"),
    ],
)
def test_deterministic_category_fixtures(
    name: str,
    raw_type: str,
    display: str,
    category: str,
) -> None:
    classified = classify_instrument(_instrument(name, raw_type, display))
    assert classified.category == category
    assert classified.taxonomy_version == TAXONOMY_VERSION
    assert classified.raw_type == raw_type


def test_snapshot_classification_covers_all_rows() -> None:
    snapshot = _snapshot(
        _instrument("EUR_USD", "CURRENCY", "EUR/USD"),
        _instrument("US30_USD", "CFD", "US Wall St 30"),
        _instrument("MYSTERY", "CFD", "Mystery"),
    )
    classified = classify_snapshot(snapshot)
    assert len(classified) == 3
    assert {item.category for item in classified} == {
        "CURRENCY",
        "INDEX_CFD",
        "OTHER_CFD",
    }


# ---------------------------------------------------------------------------
# AC-M04-W04-02: unknown instruments stay visible with raw values
# ---------------------------------------------------------------------------


def test_unknown_cfd_keeps_raw_value_and_basis() -> None:
    classified = classify_instrument(
        _instrument("WIDGET", "CFD", "Widget Futures Complex")
    )
    assert classified.category == "OTHER_CFD"
    assert classified.raw_type == "CFD"
    assert classified.display_name == "Widget Futures Complex"
    assert "unrecognized" in classified.basis


def test_unknown_raw_type_is_preserved() -> None:
    classified = classify_instrument(_instrument("QQQ_USD", "SHARE", "QQQ"))
    assert classified.category == "OTHER_CFD"
    assert classified.raw_type == "SHARE"


def test_unknown_instruments_remain_in_catalog_counts(
    tmp_path: Path,
) -> None:
    """Unknown instruments never disappear from the persisted catalog."""
    from datetime import UTC, datetime

    store = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    try:
        snapshot = InstrumentCatalogSnapshot(
            account_id_hash="acct-hash",
            fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
            instruments=(
                _instrument("EUR_USD", "CURRENCY", "EUR/USD"),
                _instrument("WIDGET", "CFD", "Widget Futures Complex"),
            ),
        )
        store.publish_snapshot(snapshot)
        projection = store.current_projection()
        assert projection is not None
        names = {i.name for i in projection.instruments}
        assert "WIDGET" in names
        assert len(projection.instruments) == 2
        # Classification over the stored projection still sees it.
        stored_snapshot = parse_instruments_response(
            {
                "instruments": [
                    {
                        "name": i.name,
                        "displayName": i.display_name,
                        "type": i.raw_type,
                        "displayPrecision": i.display_precision,
                        "tradeUnitsPrecision": i.trade_units_precision,
                        "pipLocation": i.pip_location,
                        "minimumTradeSize": str(i.minimum_trade_size),
                        "marginRate": str(i.margin_rate),
                    }
                    for i in projection.instruments
                ]
            },
            account_id="acct-hash",
        )
        classified = classify_snapshot(stored_snapshot)
        by_name = {item.name: item for item in classified}
        assert by_name["WIDGET"].category == "OTHER_CFD"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC-M04-W04-03: taxonomy is derived and versioned, never mutating raw data
# ---------------------------------------------------------------------------


def test_classification_never_mutates_raw_instrument() -> None:
    instrument = _instrument("US30_USD", "CFD", "US Wall St 30")
    before = instrument.model_dump()
    classify_instrument(instrument)
    assert instrument.model_dump() == before


def test_taxonomy_version_is_stable_and_derived() -> None:
    classified = classify_instrument(_instrument("EUR_USD", "CURRENCY", "EUR/USD"))
    assert isinstance(classified, ClassifiedInstrument)
    assert classified.taxonomy_version.startswith("oanda-taxonomy-")
