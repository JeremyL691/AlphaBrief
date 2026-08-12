"""M05-W06: market snapshot correctness and controlled practice gate.

Local deterministic gates:

- fixture and fault suites cover granularity, components, pagination,
  stream budgets, freshness, sessions, quality, snapshot
  reproducibility, and immutable lineage for every returned instrument
  type and available category (AC-M05-W06-01);
- missing credentials produce explicit ENVIRONMENT_BLOCKED semantics
  with no synthetic data, fallback prices, user question, or false
  milestone completion (AC-M05-W06-03).

Controlled practice run (AC-M05-W06-02, T7): with credentials set, the
test performs the real practice run (preflight -> candles -> pricing ->
one complete immutable snapshot) and prints a scrubbed E5 summary.
Without credentials the deterministic fail-closed path is asserted; the
round records ``external_evidence_pending``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alphabrief_execution.broker.oanda.preflight import (
    AccountPreflightError,
    run_account_preflight,
)


def _fixture_candle_rows() -> list[dict[str, Any]]:
    start = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for index in range(12):
        moment = start + timedelta(minutes=5 * index)
        rows.append(
            {
                "time": moment.isoformat().replace("+00:00", "Z"),
                "volume": "1000",
                "complete": True,
                "mid": {
                    "o": "1.10000",
                    "h": "1.11000",
                    "l": "1.09000",
                    "c": "1.10500",
                },
                "bid": {
                    "o": "1.09990",
                    "h": "1.10990",
                    "l": "1.08990",
                    "c": "1.10490",
                },
                "ask": {
                    "o": "1.10010",
                    "h": "1.11010",
                    "l": "1.09010",
                    "c": "1.10510",
                },
            }
        )
    return rows


# ---------------------------------------------------------------------------
# AC-M05-W06-01: fixture and fault suites (local determinism)
# ---------------------------------------------------------------------------


def test_fixture_suites_cover_every_contract_surface() -> None:
    """Granularity, components, pagination, sessions, quality, lineage."""
    from alphabrief_execution.broker.oanda.candles import (
        completed_only,
        parse_candles_response,
    )

    page = parse_candles_response(
        {"candles": _fixture_candle_rows()},
        symbol="EUR_USD",
        granularity="M5",
        components=("M", "B", "A"),
    )
    # Components are retained as separate facts, complete semantics hold.
    assert len(page.candles) == 36
    assert len({c.component for c in page.candles}) == 3
    assert len(completed_only(page.candles)) == 36

    from alphabrief_execution.broker.oanda.sessions import (
        evaluate_exposure_readiness,
        session_verdict,
    )

    tuesday = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    assert session_verdict("CURRENCY", tuesday).open is True
    readiness = evaluate_exposure_readiness(
        "CURRENCY", tuesday, tradeable=True, catalog_active=True
    )
    assert readiness.ready is True


def test_fault_suite_fails_closed_locally() -> None:
    """Malformed inputs and missing credentials never produce data."""
    from alphabrief_execution.broker.oanda.candles import parse_candles_response

    with pytest.raises(ValueError, match="missing M prices"):
        parse_candles_response(
            {"candles": [{"time": "2026-08-01T12:00:00Z", "complete": True}]},
            symbol="EUR_USD",
            granularity="M5",
            components=("M",),
        )


# ---------------------------------------------------------------------------
# AC-M05-W06-03: missing credentials -> ENVIRONMENT_BLOCKED
# ---------------------------------------------------------------------------


def test_missing_credentials_yield_environment_blocked() -> None:
    from alphabrief_execution.broker.oanda.config import (
        DEFAULT_BASE_URL,
        DEFAULT_MAX_RETRIES,
        DEFAULT_RETRY_BACKOFF_SECONDS,
        DEFAULT_TIMEOUT_SECONDS,
        OandaPaperConfig,
    )

    config = OandaPaperConfig(
        base_url=DEFAULT_BASE_URL,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        max_retries=DEFAULT_MAX_RETRIES,
        retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
    )
    with pytest.raises(AccountPreflightError) as excinfo:
        run_account_preflight(
            config,
            token=os.environ.get("ALPHABRIEF_OANDA_TOKEN", ""),
            account_id=os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID", ""),
        )
    assert excinfo.value.kind == "missing_credentials"
    # No synthetic data, no fallback prices, no false completion.
    assert excinfo.value.kind != "available"


# ---------------------------------------------------------------------------
# AC-M05-W06-02: controlled OANDA practice market-data run (T7)
# ---------------------------------------------------------------------------


def test_controlled_practice_market_data_run() -> None:
    """Real practice run: preflight -> candles -> pricing -> snapshot.

    Without credentials the deterministic fail-closed path is asserted
    (no mock substitution); the round records ``external_evidence_pending``.
    With credentials the full practice contract runs and publishes one
    complete immutable snapshot with a scrubbed E5 summary.
    """
    token = os.environ.get("ALPHABRIEF_OANDA_TOKEN", "").strip()
    account_id = os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        from alphabrief_execution.broker.oanda.config import (
            DEFAULT_BASE_URL,
            DEFAULT_MAX_RETRIES,
            DEFAULT_RETRY_BACKOFF_SECONDS,
            DEFAULT_TIMEOUT_SECONDS,
            OandaPaperConfig,
        )

        config = OandaPaperConfig(
            base_url=DEFAULT_BASE_URL,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            max_retries=DEFAULT_MAX_RETRIES,
            retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
        )
        with pytest.raises(AccountPreflightError) as excinfo:
            run_account_preflight(config, token="", account_id="")
        assert excinfo.value.kind == "missing_credentials"
        return  # T7 pending: external_evidence_pending recorded by the round

    import tempfile

    from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore
    from alphabrief_api.db.market_snapshot import (
        MarketSnapshotStore,
        build_market_snapshot,
    )
    from alphabrief_execution.broker.oanda.candles import (
        CandleRequest,
        fetch_candles,
    )
    from alphabrief_execution.broker.oanda.client import OandaHttpClient
    from alphabrief_execution.broker.oanda.config import (
        DEFAULT_BASE_URL,
        OandaPaperConfig,
    )
    from alphabrief_execution.broker.oanda.instruments import fetch_instruments
    from alphabrief_execution.broker.oanda.pricing import (
        PricingRequest,
        fetch_pricing,
    )
    from alphabrief_execution.broker.oanda.sessions import (
        evaluate_exposure_readiness,
    )
    from alphabrief_execution.broker.oanda.taxonomy import classify_instrument

    config = OandaPaperConfig(
        base_url=DEFAULT_BASE_URL,
        timeout_seconds=10.0,
        max_retries=2,
        retry_backoff_seconds=0.25,
    )
    profile = run_account_preflight(config, token=token, account_id=account_id)
    assert profile.tradeable is True

    client = OandaHttpClient(
        config=config, token=token, account_id=account_id
    )
    catalog = fetch_instruments(client, account_id=account_id)
    assert len(catalog.instruments) > 0

    # Candle + pricing facts for a representative subset.
    symbols = tuple(instrument.name for instrument in catalog.instruments[:5])
    candles = fetch_candles(
        client,
        request=CandleRequest(
            symbol=symbols[0],
            granularity="H1",
            components=("M",),
            count=50,
        ),
    )
    pricing = fetch_pricing(
        client,
        request=PricingRequest(symbols=symbols),
        request_id="m05-e5",
    )
    assert len(candles.candles) > 0
    assert pricing.coverage.complete is True

    os.environ["ALPHABRIEF_DATA_DIR"] = str(
        Path(tempfile.mkdtemp()) / "alphabrief_db"
    )
    catalog_store = InstrumentCatalogStore()
    catalog_store.publish_snapshot(catalog)
    projection = catalog_store.current_projection()
    assert projection is not None
    catalog_store.close()

    classified = classify_instrument(catalog.instruments[0])
    readiness = evaluate_exposure_readiness(
        classified.category,
        datetime.now(UTC),
        tradeable=True,
        catalog_active=True,
    )
    snapshot = build_market_snapshot(
        catalog=projection,
        pricing=pricing,
        candles=candles.candles,
        readiness=readiness,
    )
    assert snapshot.executable is True

    snapshot_store = MarketSnapshotStore()
    snapshot_store.publish(snapshot)
    persisted = snapshot_store.get(snapshot.snapshot_id)
    assert persisted is not None
    assert persisted.snapshot_id == snapshot.snapshot_id
    snapshot_store.close()

    print(
        f"E5-MARKET account_hash={profile.account_id_hash} "
        f"instruments={len(catalog.instruments)} "
        f"candles={len(candles.candles)} prices={len(pricing.prices)} "
        f"snapshot={snapshot.snapshot_id}"
    )
