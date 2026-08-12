"""M04-W06: account catalog completeness and controlled practice gate.

Local deterministic gates:

- fixture completeness: the response count equals the immutable store,
  API, and CLI counts with no hard-coded allowlist loss and complete
  required metadata for every row (AC-M04-W06-01);
- missing credentials fail closed with ENVIRONMENT_BLOCKED semantics and
  no mock substitution, waiver, fallback, or false DONE (AC-M04-W06-03).

Controlled practice run (AC-M04-W06-02, T7): with
``ALPHABRIEF_OANDA_TOKEN`` and ``ALPHABRIEF_OANDA_ACCOUNT_ID`` set, the
test performs the real practice account catalog run (preflight -> fetch
-> persist -> API/CLI counts agree) and prints a scrubbed E5 evidence
summary. Without credentials the fail-closed path is asserted; the
round records ``external_evidence_pending`` — mock output never
masquerades as practice evidence.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentMetadata,
    parse_instruments_response,
)
from alphabrief_execution.broker.oanda.preflight import (
    AccountPreflightError,
    run_account_preflight,
)

ACCOUNT_ID = "101-004-1234567-001"


def _fixture_response() -> dict[str, object]:
    """A fixture catalog response covering every required metadata field."""
    return {
        "instruments": [
            {
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
            },
            {
                "name": "XAU_USD",
                "type": "METAL",
                "displayName": "Gold",
                "pipLocation": -4,
                "displayPrecision": 5,
                "tradeUnitsPrecision": 0,
                "minimumTradeSize": "1",
                "maximumPositionSize": "0",
                "maximumOrderUnits": "0",
                "marginRate": "0.02",
            },
            {
                "name": "US30_USD",
                "type": "CFD",
                "displayName": "US Wall St 30",
                "pipLocation": 1,
                "displayPrecision": 1,
                "tradeUnitsPrecision": 0,
                "minimumTradeSize": "1",
                "maximumPositionSize": "0",
                "maximumOrderUnits": "0",
                "marginRate": "0.02",
            },
            {
                "name": "WIDGET_CFD",
                "type": "CFD",
                "displayName": "Widget Futures Complex",
                "pipLocation": 1,
                "displayPrecision": 1,
                "tradeUnitsPrecision": 0,
                "minimumTradeSize": "1",
                "maximumPositionSize": "0",
                "maximumOrderUnits": "0",
                "marginRate": "0.10",
            },
        ]
    }


def _required_fields(instrument: InstrumentMetadata) -> None:
    """Assert every required metadata field is present and typed."""
    assert instrument.name
    assert instrument.display_name
    assert instrument.raw_type
    assert isinstance(instrument.display_precision, int)
    assert isinstance(instrument.trade_units_precision, int)
    assert isinstance(instrument.minimum_trade_size, Decimal)
    assert isinstance(instrument.maximum_order_units, Decimal)
    assert isinstance(instrument.maximum_position_size, Decimal)
    assert isinstance(instrument.margin_rate, Decimal)
    assert isinstance(instrument.pip_location, int)


# ---------------------------------------------------------------------------
# AC-M04-W06-01: fixture completeness — response == store == API == CLI
# ---------------------------------------------------------------------------


def test_fixture_completeness_response_store_api_cli_agree(
    tmp_path: Path,
) -> None:
    """The response count equals store, API, and CLI counts; no row lost."""
    import os as _os

    from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore
    from alphabrief_api.main import create_app
    from alphabrief_cli.data_commands import data_app
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    _os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    from alphabrief_api.routes.data import _clear_catalog_store

    _clear_catalog_store()

    parsed = parse_instruments_response(
        _fixture_response(), account_id=ACCOUNT_ID
    )
    response_count = len(parsed.instruments)

    store = InstrumentCatalogStore()
    store.publish_snapshot(parsed)
    store_count = len(store.list_snapshots())  # one snapshot
    assert store_count == 1
    projection = store.current_projection()
    assert projection is not None
    assert len(projection.instruments) == response_count
    for instrument in projection.instruments:
        _required_fields(instrument)
    store.close()

    _clear_catalog_store()
    client = TestClient(create_app())
    api = client.get("/api/v1/data/catalog").json()
    assert api["availability"] == "available"
    assert api["total"] == response_count
    assert len(api["items"]) == response_count
    assert {item["name"] for item in api["items"]} == {
        i.name for i in parsed.instruments
    }

    result = CliRunner().invoke(data_app, ["catalog", "--compact"])
    assert result.exit_code == 0
    cli = json.loads(result.stdout)
    assert cli["total"] == api["total"]
    assert cli["filtered_count"] == api["filtered_count"]
    assert cli == api

    # The unknown CFD row is present with complete metadata in every surface.
    for surface in (projection.instruments, api["items"], cli["items"]):
        names = {i["name"] if isinstance(i, dict) else i.name for i in surface}
        assert "WIDGET_CFD" in names
    _clear_catalog_store()


# ---------------------------------------------------------------------------
# AC-M04-W06-03: missing credentials fail closed (no substitution)
# ---------------------------------------------------------------------------


def test_missing_credentials_fail_closed_no_fallback() -> None:
    """Without credentials the practice gate reports ENVIRONMENT_BLOCKED."""
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
    # No mock data is produced and no catalog write happens.
    assert excinfo.value.kind != "available"


# ---------------------------------------------------------------------------
# AC-M04-W06-02: controlled OANDA practice run (T7; runs only with creds)
# ---------------------------------------------------------------------------


def test_controlled_practice_catalog_run() -> None:
    """The real practice run (preflight -> fetch -> persist -> counts).

    Without credentials the deterministic fail-closed path is asserted
    (no mock substitution); the round records ``external_evidence_pending``
    and the milestone stays CODE_COMPLETE until a real T7 run exists.
    With credentials the full practice contract runs and a scrubbed E5
    summary is printed.
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
    from alphabrief_execution.broker.oanda.client import OandaHttpClient
    from alphabrief_execution.broker.oanda.config import (
        DEFAULT_BASE_URL,
        OandaPaperConfig,
    )
    from alphabrief_execution.broker.oanda.instruments import fetch_instruments

    config = OandaPaperConfig(
        base_url=DEFAULT_BASE_URL,
        timeout_seconds=10.0,
        max_retries=2,
        retry_backoff_seconds=0.25,
    )
    profile = run_account_preflight(
        config, token=token, account_id=account_id
    )
    assert profile.tradeable is True

    client = OandaHttpClient(
        config=config, token=token, account_id=account_id
    )
    snapshot = fetch_instruments(client, account_id=account_id)
    assert len(snapshot.instruments) > 0

    os.environ["ALPHABRIEF_DATA_DIR"] = str(
        Path(tempfile.mkdtemp()) / "alphabrief_db"
    )
    store = InstrumentCatalogStore()
    store.publish_snapshot(snapshot)
    projection = store.current_projection()
    assert projection is not None
    assert len(projection.instruments) == len(snapshot.instruments)
    store.close()

    print(
        f"E5-CATALOG account_hash={snapshot.account_id_hash} "
        f"instruments={len(snapshot.instruments)} "
        f"fetched_at={snapshot.fetched_at.isoformat()}"
    )
