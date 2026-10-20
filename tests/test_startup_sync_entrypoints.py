"""Startup recovery is invoked by every runtime entry point (GUIDE 5.8).

A crash between the broker accepting an order and the caller persisting
the result leaves an in-flight reservation in the durable ledger. Before
the process may submit anything new it must settle that reservation by
querying the broker; an unexplainable outcome freezes new exposure and
the entry point fails closed.
"""

from __future__ import annotations

import pytest
from alphabrief_api.routes import ai_trading
from alphabrief_cli import ai_commands, cycle_commands
from alphabrief_execution.broker.oanda.submit_recovery import StartupSyncResult
from alphabrief_trader import ExternalPaperExecutionBackend
from fastapi import HTTPException


class _SyncBackend(ExternalPaperExecutionBackend):
    """Backend double whose startup recovery verdict is scripted."""

    def __init__(
        self,
        *,
        result: StartupSyncResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._sync_result = result
        self._sync_error = error
        self.sync_calls = 0

    def startup_sync(self) -> StartupSyncResult | None:
        self.sync_calls += 1
        if self._sync_error is not None:
            raise self._sync_error
        return self._sync_result


def _result(*, frozen: tuple[str, ...] = ()) -> StartupSyncResult:
    return StartupSyncResult(
        account_id="101-004-1234567-001",
        in_flight_found=len(frozen) or 1,
        completed=() if frozen else ("cycle:intent",),
        frozen=frozen,
        mappings_restored=0,
        cursor=None,
        frozen_exposure=bool(frozen),
    )


class TestCliStartupSync:
    def test_settled_in_flight_does_not_block_the_run(self) -> None:
        backend = _SyncBackend(result=_result())
        cycle_commands._startup_sync_or_exit(backend)
        assert backend.sync_calls == 1

    def test_unresolved_outcome_exits_before_any_submit(self) -> None:
        backend = _SyncBackend(result=_result(frozen=("cycle:intent",)))
        with pytest.raises(SystemExit) as excinfo:
            cycle_commands._startup_sync_or_exit(backend)
        assert excinfo.value.code == 1

    def test_query_failure_exits_instead_of_trading_blind(self) -> None:
        backend = _SyncBackend(error=RuntimeError("broker unreachable"))
        with pytest.raises(SystemExit) as excinfo:
            cycle_commands._startup_sync_or_exit(backend)
        assert excinfo.value.code == 1

    def test_ai_run_uses_the_same_recovery_gate(self) -> None:
        backend = _SyncBackend(result=_result(frozen=("cycle:intent",)))
        with pytest.raises(SystemExit) as excinfo:
            ai_commands._startup_sync_or_exit(backend)
        assert excinfo.value.code == 1


class TestApiStartupSync:
    def test_settled_in_flight_does_not_block_the_run(self) -> None:
        backend = _SyncBackend(result=_result())
        ai_trading._startup_sync(backend)
        assert backend.sync_calls == 1

    def test_unresolved_outcome_refuses_new_exposure(self) -> None:
        backend = _SyncBackend(result=_result(frozen=("cycle:intent",)))
        with pytest.raises(HTTPException) as excinfo:
            ai_trading._startup_sync(backend)
        assert excinfo.value.status_code == 409
        assert "frozen" in str(excinfo.value.detail)

    def test_query_failure_returns_service_unavailable(self) -> None:
        backend = _SyncBackend(error=RuntimeError("broker unreachable"))
        with pytest.raises(HTTPException) as excinfo:
            ai_trading._startup_sync(backend)
        assert excinfo.value.status_code == 503
