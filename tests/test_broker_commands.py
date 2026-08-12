"""Unit tests for the CLI broker commands and the shared OANDA runtime.

M01-W04: the API lifespan, CLI broker commands, and the scheduler resolve
one runtime factory and one persistent data directory authority
(AC-M01-W04-01); entry points cannot expose conflicting in-memory account
state (AC-M01-W04-02); shutdown closes clients and stores without
discarding durable mappings (AC-M01-W04-03).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    """Ensure each test starts and ends with a cleared shared runtime."""
    from alphabrief_execution.broker.runtime import reset_broker_runtime

    reset_broker_runtime()
    yield
    reset_broker_runtime()


def test_open_store_uses_persistent_data_directory_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M01-W04-01: CLI broker commands use the persistent data dir."""
    from alphabrief_cli.broker_commands import _open_store
    from alphabrief_execution.broker.runtime import resolve_data_dir

    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    assert resolve_data_dir() == tmp_path

    store = _open_store()
    try:
        assert (tmp_path / "alphabrief.db").is_file()
    finally:
        store.close()


def test_status_cmd_prints_offline_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI broker status reads the local recon store when the API is down."""
    from alphabrief_cli.broker_commands import status_cmd

    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    status_cmd(pretty=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["latest_snapshot"] is None
    assert payload["open_freeze_count"] == 0


def test_reconcile_cmd_records_offline_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI broker reconcile records a deterministic offline snapshot."""
    from alphabrief_cli.broker_commands import reconcile_cmd
    from alphabrief_execution.broker.recon_store import BrokerReconStore

    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    reconcile_cmd(scope="cycle", pretty=False)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["scope"] == "cycle"
    assert payload["all_match"] is True
    assert payload["snapshot_id"]

    store = BrokerReconStore(db_path=tmp_path / "alphabrief.db")
    try:
        latest = store.latest_snapshot(scope="cycle")
        assert latest is not None
        assert latest.all_match is True
    finally:
        store.close()


def test_reconcile_cmd_rejects_invalid_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    from alphabrief_cli.broker_commands import reconcile_cmd

    with pytest.raises(SystemExit) as excinfo:
        reconcile_cmd(scope="bogus", pretty=False)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "--scope" in captured.err


def test_entry_points_resolve_one_shared_runtime_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M01-W04-02: API and scheduler expose the same in-memory adapter."""
    from alphabrief_api import broker_adapter
    from alphabrief_cli.scheduler_commands import _build_adapter
    from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter

    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", "test-token")
    monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("ALPHABRIEF_OANDA_BASE_URL", "http://127.0.0.1:1")

    api_adapter = broker_adapter.get_broker_adapter()
    scheduler_adapter = _build_adapter()

    assert isinstance(api_adapter, OandaPaperAdapter)
    assert api_adapter is scheduler_adapter
    # In-memory idempotency state is shared: registering through one entry
    # point is visible through the other.
    api_adapter.register_known_mapping(
        client_order_id="shared-client-1", broker_order_id="shared-broker-1"
    )
    assert scheduler_adapter.known_mappings() == {"shared-client-1": "shared-broker-1"}


def test_shutdown_flushes_durable_mappings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M01-W04-03: close() persists mappings instead of discarding them."""
    from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
    from alphabrief_execution.broker.recon_store import BrokerReconStore
    from alphabrief_execution.broker.runtime import BrokerRuntime

    monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", "test-token")
    monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("ALPHABRIEF_OANDA_BASE_URL", "http://127.0.0.1:1")

    runtime = BrokerRuntime(data_dir=tmp_path)
    adapter = runtime.adapter
    assert isinstance(adapter, OandaPaperAdapter)
    adapter.register_known_mapping(
        client_order_id="flush-client-1", broker_order_id="flush-broker-1"
    )

    runtime.close()

    store = BrokerReconStore(db_path=tmp_path / "alphabrief.db")
    try:
        rows = store.list_order_id_map()
        assert {row["client_order_id"]: row["broker_order_id"] for row in rows} == {
            "flush-client-1": "flush-broker-1"
        }
    finally:
        store.close()


def test_runtime_is_process_scoped_singleton(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M01-W04-01: one runtime factory per process with one data dir."""
    from alphabrief_execution.broker.runtime import (
        get_broker_runtime,
        resolve_data_dir,
    )

    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    assert get_broker_runtime().data_dir == resolve_data_dir() == tmp_path
    assert get_broker_runtime() is get_broker_runtime()
