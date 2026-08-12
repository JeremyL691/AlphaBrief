"""M05-W04: instrument-level session integration with catalog state.

Session verdicts combine with persisted catalog state (active/inactive
and taxonomy category) so new-exposure readiness derives from account
truth rather than a global weekday window.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentCatalogSnapshot,
    InstrumentMetadata,
)
from alphabrief_execution.broker.oanda.sessions import (
    evaluate_exposure_readiness,
    session_verdict,
)
from alphabrief_execution.broker.oanda.taxonomy import classify_instrument

TUESDAY = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
SUNDAY = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)


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


def test_instrument_category_drives_session_readiness(
    tmp_path: Path,
) -> None:
    """Catalog taxonomy determines the session that applies to an instrument."""
    store = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    try:
        store.publish_snapshot(
            InstrumentCatalogSnapshot(
                account_id_hash="acct-hash",
                fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
                instruments=(
                    _instrument("EUR_USD", "CURRENCY", "EUR/USD"),
                    _instrument("XBT_USD", "CFD", "Bitcoin"),
                    _instrument("US30_USD", "CFD", "US Wall St 30"),
                ),
            )
        )
        projection = store.current_projection()
        assert projection is not None
    finally:
        store.close()

    by_name = {i.name: i for i in projection.instruments}
    categories = {
        name: classify_instrument(instrument).category
        for name, instrument in by_name.items()
    }
    assert categories["EUR_USD"] == "CURRENCY"
    assert categories["XBT_USD"] == "CRYPTO_CFD"
    assert categories["US30_USD"] == "INDEX_CFD"

    # A Sunday: crypto stays ready, currency and index CFD close.
    for category in categories.values():
        readiness = evaluate_exposure_readiness(
            category,
            SUNDAY,
            tradeable=True,
            catalog_active=True,
        )
        if category == "CRYPTO_CFD":
            assert readiness.ready is True
        else:
            assert readiness.ready is False

    # A Tuesday: all categories open.
    for category in categories.values():
        readiness = evaluate_exposure_readiness(
            category,
            TUESDAY,
            tradeable=True,
            catalog_active=True,
        )
        assert readiness.ready is True


def test_inactive_catalog_instrument_fails_closed_for_new_exposure(
    tmp_path: Path,
) -> None:
    """An instrument outside the current projection is not ready."""
    verdict = session_verdict("CURRENCY", TUESDAY)
    assert verdict.open is True
    readiness = evaluate_exposure_readiness(
        "CURRENCY",
        TUESDAY,
        tradeable=True,
        catalog_active=False,
    )
    assert readiness.ready is False
    assert "inactive" in readiness.reason
