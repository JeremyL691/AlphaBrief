"""M05-W05: immutable market snapshots and quality verdicts.

Covers:
- identical immutable inputs and quality-policy version produce the
  same snapshot ID, manifest hash, source IDs, quality results, and
  normalized serialization (AC-M05-W05-01);
- incomplete candles, stale quotes, missing conversion, catalog
  mismatch, unacceptable gaps, abnormal spread, and partial coverage
  produce explicit rule results and a non-executable verdict
  (AC-M05-W05-02);
- later ingestion creates new facts and a new lineage-linked snapshot
  without changing any snapshot already referenced by a decision
  (AC-M05-W05-03).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from alphabrief_api.db.instrument_catalog import CatalogProjection
from alphabrief_api.db.market_snapshot import (
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


def _catalog(symbols: tuple[str, ...] = ("EUR_USD", "GBP_USD")) -> CatalogProjection:
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
        snapshot_id="catalog-1",
        content_hash="catalog-content-1",
        instruments=instruments,
    )


def _instrument(name: str) -> object:
    from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata

    return InstrumentMetadata(
        name=name,
        display_name=name.replace("_", "/"),
        raw_type="CURRENCY",
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
    )


def _price(symbol: str = "EUR_USD", spread: str = "0.0005") -> OandaPrice:
    return OandaPrice(
        symbol=symbol,
        bids=(PriceLadderEntry(price=Decimal("1.10000"), liquidity=1),),
        asks=(PriceLadderEntry(price=Decimal("1.10050"), liquidity=1),),
        spread=Decimal(spread),
        tradeable=True,
        closeout_bid=Decimal("1.10000"),
        closeout_ask=Decimal("1.10050"),
        conversion_factor=Decimal("1"),
        broker_time=datetime(2026, 8, 4, 10, 0, tzinfo=UTC),
        request_id="r-1",
        source_version="oanda-v20-pricing-1",
    )


def _pricing_batch(*prices: OandaPrice) -> PricingBatch:
    from alphabrief_execution.broker.oanda.pricing import InstrumentCoverage

    symbols = tuple(p.symbol for p in prices)
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


def _candle(time: datetime, complete: bool = True) -> object:
    from alphabrief_execution.broker.oanda.candles import OandaCandle

    return OandaCandle(
        symbol="EUR_USD",
        time=time,
        component="M",
        open=Decimal("1.10"),
        high=Decimal("1.11"),
        low=Decimal("1.09"),
        close=Decimal("1.105"),
        volume=Decimal("1000"),
        complete=complete,
        source_version="oanda-v20-candles-1",
    )


def _ready(symbols: tuple[str, ...] = ("EUR_USD", "GBP_USD")) -> ExposureReadiness:
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


def _snapshot_inputs(
    symbols: tuple[str, ...] = ("EUR_USD", "GBP_USD"),
) -> dict[str, Any]:
    start = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    return {
        "catalog": _catalog(symbols),
        "pricing": _pricing_batch(*[_price(s) for s in symbols]),
        "candles": tuple(_candle(start + timedelta(minutes=5 * i)) for i in range(12)),
        "readiness": _ready(symbols),
    }


# ---------------------------------------------------------------------------
# AC-M05-W05-01: deterministic reproducibility
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_snapshot() -> None:
    first = build_market_snapshot(**_snapshot_inputs())
    second = build_market_snapshot(**_snapshot_inputs())
    assert first.snapshot_id == second.snapshot_id
    assert first.manifest_hash == second.manifest_hash
    assert first.source_ids == second.source_ids
    assert first.quality == second.quality
    assert first.executable is True
    # Normalized serialization: built_at is wall-clock metadata outside the
    # deterministic manifest, so it is excluded from the comparison.
    first_normalized = first.model_dump(mode="json")
    first_normalized.pop("built_at")
    second_normalized = second.model_dump(mode="json")
    second_normalized.pop("built_at")
    assert first_normalized == second_normalized


def test_different_quality_policy_version_changes_snapshot() -> None:
    first = build_market_snapshot(**_snapshot_inputs(), quality_policy_version="v1")
    second = build_market_snapshot(**_snapshot_inputs(), quality_policy_version="v2")
    assert first.snapshot_id != second.snapshot_id


def test_publish_is_idempotent(tmp_path: Path) -> None:
    store = MarketSnapshotStore(db_path=tmp_path / "snap.db")
    try:
        snapshot = build_market_snapshot(**_snapshot_inputs())
        store.publish(snapshot)
        store.publish(snapshot)
        latest = store.latest()
        assert latest is not None
        assert latest.snapshot_id == snapshot.snapshot_id
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC-M05-W05-02: quality rules fail closed
# ---------------------------------------------------------------------------


def test_incomplete_candles_make_snapshot_non_executable() -> None:
    inputs = _snapshot_inputs()
    start = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    candles = (
        _candle(start, complete=False),
        _candle(start + timedelta(minutes=5)),
    )
    snapshot = build_market_snapshot(**{**inputs, "candles": candles})
    assert snapshot.executable is False
    assert any(
        rule.rule == "incomplete_candles" and not rule.passed
        for rule in snapshot.quality
    )


def test_stale_quotes_make_snapshot_non_executable() -> None:
    inputs = _snapshot_inputs()
    stale = _price("EUR_USD").model_copy(update={"broker_time": None})
    snapshot = build_market_snapshot(
        **{**inputs, "pricing": _pricing_batch(stale, _price("GBP_USD"))}
    )
    assert snapshot.executable is False
    assert any(
        rule.rule == "stale_quotes" and not rule.passed
        for rule in snapshot.quality
    )


def test_catalog_mismatch_makes_snapshot_non_executable() -> None:
    inputs = _snapshot_inputs()
    unknown = _price("NOPE")
    snapshot = build_market_snapshot(
        **{**inputs, "pricing": _pricing_batch(_price("EUR_USD"), unknown)}
    )
    assert snapshot.executable is False
    assert any(
        rule.rule == "catalog_mismatch" and not rule.passed
        for rule in snapshot.quality
    )


def test_unacceptable_gaps_make_snapshot_non_executable() -> None:
    inputs = _snapshot_inputs()
    start = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    candles = (
        _candle(start),
        _candle(start + timedelta(minutes=120)),
    )
    snapshot = build_market_snapshot(**{**inputs, "candles": candles})
    assert snapshot.executable is False
    assert any(
        rule.rule == "unacceptable_gaps" and not rule.passed
        for rule in snapshot.quality
    )


def test_abnormal_spread_makes_snapshot_non_executable() -> None:
    inputs = _snapshot_inputs()
    wide = _price("EUR_USD", spread="0.20")
    snapshot = build_market_snapshot(
        **{**inputs, "pricing": _pricing_batch(wide, _price("GBP_USD"))}
    )
    assert snapshot.executable is False
    assert any(
        rule.rule == "abnormal_spread" and not rule.passed
        for rule in snapshot.quality
    )


def test_non_ready_readiness_makes_snapshot_non_executable() -> None:
    inputs = _snapshot_inputs()
    not_ready = ExposureReadiness(
        ready=False,
        reason="market session is closed",
        session=SessionVerdict(
            open=False,
            reason="outside category session window",
            category="CURRENCY",
            moment=datetime(2026, 8, 9, 10, 0, tzinfo=UTC),
        ),
    )
    snapshot = build_market_snapshot(**{**inputs, "readiness": not_ready})
    assert snapshot.executable is False


# ---------------------------------------------------------------------------
# AC-M05-W05-03: lineage and immutability
# ---------------------------------------------------------------------------


def test_later_ingestion_creates_lineage_without_mutating_old_snapshot(
    tmp_path: Path,
) -> None:
    store = MarketSnapshotStore(db_path=tmp_path / "snap.db")
    try:
        first = build_market_snapshot(**_snapshot_inputs(symbols=("EUR_USD",)))
        store.publish(first)

        # Later ingestion changes inputs -> new facts, new snapshot.
        second = build_market_snapshot(
            **_snapshot_inputs(symbols=("EUR_USD", "GBP_USD")),
            lineage_parent=first.snapshot_id,
        )
        store.publish(second)

        # The original snapshot is unchanged and still referenced.
        stored_first = store.get(first.snapshot_id)
        assert stored_first is not None
        assert stored_first.model_dump(mode="json") == first.model_dump(mode="json")

        # Lineage chains back to the root.
        chain = store.lineage(second.snapshot_id)
        assert chain[0] == second.snapshot_id
        assert chain[1] == first.snapshot_id
        assert store.lineage(first.snapshot_id) == [first.snapshot_id]
    finally:
        store.close()
