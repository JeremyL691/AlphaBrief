"""M05-W05: market snapshot lineage (AC-M05-W05-03).

Later ingestion or correction creates new facts and a new lineage-linked
snapshot without changing any snapshot already referenced by a decision.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alphabrief_api.db.instrument_catalog import CatalogProjection
from alphabrief_api.db.market_snapshot import (
    MarketSnapshot,
    MarketSnapshotStore,
    build_market_snapshot,
)
from alphabrief_execution.broker.oanda.pricing import (
    OandaPrice,
    PriceLadderEntry,
    PricingBatch,
)
from alphabrief_execution.broker.oanda.sessions import (
    ExposureReadiness,
    SessionVerdict,
)


def _catalog(symbols: tuple[str, ...]) -> CatalogProjection:
    from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata

    instruments = tuple(
        InstrumentMetadata(
            name=symbol,
            display_name=symbol.replace("_", "/"),
            raw_type="CURRENCY",
            display_precision=5,
            trade_units_precision=0,
            minimum_trade_size=Decimal("1"),
            maximum_order_units=Decimal("0"),
            maximum_position_size=Decimal("0"),
            margin_rate=Decimal("0.05"),
            pip_location=-4,
        )
        for symbol in symbols
    )
    return CatalogProjection(
        account_id_hash="acct-hash",
        snapshot_id="catalog-" + "-".join(symbols),
        content_hash="content-" + "-".join(symbols),
        instruments=instruments,
    )


def _price(symbol: str) -> OandaPrice:
    return OandaPrice(
        symbol=symbol,
        bids=(PriceLadderEntry(price=Decimal("1.10"), liquidity=1),),
        asks=(PriceLadderEntry(price=Decimal("1.105"), liquidity=1),),
        spread=Decimal("0.005"),
        tradeable=True,
        closeout_bid=Decimal("1.10"),
        closeout_ask=Decimal("1.105"),
        conversion_factor=Decimal("1"),
        broker_time=datetime(2026, 8, 4, 10, 0, tzinfo=UTC),
        request_id="r",
        source_version="oanda-v20-pricing-1",
    )


def _pricing(*symbols: str) -> PricingBatch:
    from alphabrief_execution.broker.oanda.pricing import InstrumentCoverage

    prices = tuple(_price(s) for s in symbols)
    return PricingBatch(
        prices=prices,
        coverage=InstrumentCoverage(
            requested=symbols,
            returned=symbols,
            missing=(),
            failed=(),
            complete=True,
        ),
    )


def _candles() -> tuple[object, ...]:
    from alphabrief_execution.broker.oanda.candles import OandaCandle

    start = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    return tuple(
        OandaCandle(
            symbol="EUR_USD",
            time=start + timedelta(minutes=5 * i),
            component="M",
            open=Decimal("1.10"),
            high=Decimal("1.11"),
            low=Decimal("1.09"),
            close=Decimal("1.105"),
            volume=Decimal("1000"),
            complete=True,
            source_version="oanda-v20-candles-1",
        )
        for i in range(12)
    )


def _ready() -> ExposureReadiness:
    return ExposureReadiness(
        ready=True,
        reason="session open and instrument tradeable",
        session=SessionVerdict(
            open=True,
            reason="inside category session window",
            category="CURRENCY",
            moment=datetime(2026, 8, 4, 10, 0, tzinfo=UTC),
        ),
    )


def _build(symbols: tuple[str, ...], *, parent: str | None = None) -> MarketSnapshot:
    return build_market_snapshot(
        catalog=_catalog(symbols),
        pricing=_pricing(*symbols),
        candles=_candles(),
        readiness=_ready(),
        lineage_parent=parent,
    )


def test_lineage_chain_links_corrections(tmp_path: Path) -> None:
    store = MarketSnapshotStore(db_path=tmp_path / "snap.db")
    try:
        v1 = _build(("EUR_USD",))
        store.publish(v1)

        # A correction (new catalog, new facts) links back to v1.
        v2 = _build(("EUR_USD", "GBP_USD"), parent=v1.snapshot_id)
        store.publish(v2)

        v3 = _build(("EUR_USD", "GBP_USD", "USD_JPY"), parent=v2.snapshot_id)
        store.publish(v3)

        chain = store.lineage(v3.snapshot_id)
        assert chain == [v3.snapshot_id, v2.snapshot_id, v1.snapshot_id]

        # Snapshots referenced by decisions are immutable.
        stored_v1 = store.get(v1.snapshot_id)
        assert stored_v1 is not None
        normalized_v1 = stored_v1.model_dump(mode="json")
        normalized_v1.pop("built_at")
        normalized_original = v1.model_dump(mode="json")
        normalized_original.pop("built_at")
        assert normalized_v1 == normalized_original
    finally:
        store.close()


def test_latest_snapshot_reflects_most_recent_ingestion(tmp_path: Path) -> None:
    store = MarketSnapshotStore(db_path=tmp_path / "snap.db")
    try:
        v1 = _build(("EUR_USD",))
        store.publish(v1)
        v2 = _build(("EUR_USD", "GBP_USD"), parent=v1.snapshot_id)
        store.publish(v2)

        latest = store.latest()
        assert latest is not None
        assert latest.snapshot_id == v2.snapshot_id
        assert latest.lineage_parent == v1.snapshot_id
    finally:
        store.close()
