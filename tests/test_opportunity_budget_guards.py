"""The daily round cap and spacing must actually bound the model spend.

`_opportunity_facts` is what protects the free channel's 1000 calls/day:
it counts today's ``opportunity:`` rounds and remembers the newest one, so
``scan_opportunities`` can refuse to escalate past ``max_rounds_per_day``
or before ``min_spacing_seconds`` elapsed.

It read ``getattr(cycle, "cycle_key", None)`` off a ``DailyCycleSummary``,
which has no such field, so the prefix test never matched, ``rounds``
stayed 0 and ``last_round_at`` stayed ``None``. Both guards were dead: a
day recorded 67 and 95 opportunity rounds against a configured cap of 20,
and the model channel logged 2015 calls in one UTC day against a hard
ceiling of 1000.

These tests pin the guards to durable history, not to an in-memory
counter, so a restart cannot hand the runtime a fresh allowance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alphabrief_api.db import AiTradingStore
from alphabrief_cli.run_commands import Runtime
from alphabrief_trader.schemas import DailyCycleRecord


def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, now: datetime) -> Runtime:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    return Runtime(
        host="127.0.0.1",
        port=0,
        universe=("EUR_USD",),
        clock=lambda: now,
        decision_round=lambda key: None,
        report_writer=lambda: None,
        backup_runner=lambda: None,
        close_out=lambda reason: None,
        quote_poller=lambda: 0,
        shadow_scorer=lambda: 0,
        market_refresher=lambda: None,
        position_monitor=lambda: 0,
    )


def _record_cycle(
    store: AiTradingStore,
    *,
    cycle_id: str,
    day: str,
    created_at: datetime,
    cycle_key: str,
) -> None:
    store.save_cycle(
        DailyCycleRecord(
            cycle_id=cycle_id,
            trading_day=day,
            symbols=["EUR_USD"],
            plans=[],
            votes=[],
            attempts=[],
            outcome="skipped_no_intent",
            enabled=True,
            live_trading_enabled=False,
            summary="fixture",
            cycle_key=cycle_key,
            created_at=created_at,
        )
    )


def test_opportunity_rounds_are_counted_from_durable_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The count must see the stored rounds, not always zero."""
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    runtime = _runtime(tmp_path, monkeypatch, now)
    store = AiTradingStore(db_path=tmp_path / "alphabrief.duckdb")
    try:
        for index in range(3):
            _record_cycle(
                store,
                cycle_id=f"cyc_opp_{index}",
                day=now.date().isoformat(),
                created_at=now - timedelta(minutes=30 - index * 10),
                cycle_key=f"opportunity:20261021T11{index}0",
            )
        rounds, last = runtime._opportunity_facts()
    finally:
        store.close()

    assert rounds == 3, (
        "the round counter read a field DailyCycleSummary does not expose, "
        "so max_rounds_per_day could never bind"
    )
    assert last is not None


def test_last_round_instant_is_the_newest_opportunity_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spacing depends on this instant being the newest round, not None."""
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    runtime = _runtime(tmp_path, monkeypatch, now)
    newest = now - timedelta(minutes=5)
    store = AiTradingStore(db_path=tmp_path / "alphabrief.duckdb")
    try:
        _record_cycle(
            store,
            cycle_id="cyc_old",
            day=now.date().isoformat(),
            created_at=now - timedelta(hours=3),
            cycle_key="opportunity:20261021T0900",
        )
        _record_cycle(
            store,
            cycle_id="cyc_new",
            day=now.date().isoformat(),
            created_at=newest,
            cycle_key="opportunity:20261021T1155",
        )
        _, last = runtime._opportunity_facts()
    finally:
        store.close()

    assert last is not None
    assert abs((last - newest).total_seconds()) < 1


def test_manual_cycles_do_not_count_toward_the_opportunity_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CLI run is not an opportunity round and must not consume the cap."""
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    runtime = _runtime(tmp_path, monkeypatch, now)
    store = AiTradingStore(db_path=tmp_path / "alphabrief.duckdb")
    try:
        _record_cycle(
            store,
            cycle_id="cyc_manual",
            day=now.date().isoformat(),
            created_at=now - timedelta(minutes=5),
            cycle_key="decision_round_tokyo:2026-10-21",
        )
        rounds, last = runtime._opportunity_facts()
    finally:
        store.close()

    assert rounds == 0
    assert last is None


def test_previous_days_rounds_do_not_count_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap is per UTC day; yesterday's rounds are spent budget."""
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    runtime = _runtime(tmp_path, monkeypatch, now)
    store = AiTradingStore(db_path=tmp_path / "alphabrief.duckdb")
    try:
        _record_cycle(
            store,
            cycle_id="cyc_yesterday",
            day="2026-10-20",
            created_at=now - timedelta(days=1),
            cycle_key="opportunity:20261020T1200",
        )
        rounds, last = runtime._opportunity_facts()
    finally:
        store.close()

    assert rounds == 0
    assert last is None


def _record_outcome(
    store: AiTradingStore,
    *,
    cycle_id: str,
    day: str,
    created_at: datetime,
    outcome: Any,
) -> None:
    store.save_cycle(
        DailyCycleRecord(
            cycle_id=cycle_id,
            trading_day=day,
            symbols=["EUR_USD"],
            plans=[],
            votes=[],
            attempts=[],
            outcome=outcome,
            enabled=True,
            live_trading_enabled=False,
            summary="fixture",
            cycle_key=f"opportunity:{cycle_id}",
            created_at=created_at,
        )
    )


def test_a_run_of_provider_errors_opens_the_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three consecutive failed rounds mean the channel is down, not busy."""
    from alphabrief_cli.run_commands import PROVIDER_FAILURE_BREAKER_STREAK

    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    runtime = _runtime(tmp_path, monkeypatch, now)
    store = AiTradingStore(db_path=tmp_path / "alphabrief.duckdb")
    try:
        for index in range(PROVIDER_FAILURE_BREAKER_STREAK):
            _record_outcome(
                store,
                cycle_id=f"cyc_fail_{index}",
                day=now.date().isoformat(),
                created_at=now - timedelta(minutes=10 - index),
                outcome="provider_error",
            )
        available = runtime._provider_available()
    finally:
        store.close()

    assert available is False


def test_a_successful_round_closes_the_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The newest round decides: a recovery re-enables escalation."""
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    runtime = _runtime(tmp_path, monkeypatch, now)
    store = AiTradingStore(db_path=tmp_path / "alphabrief.duckdb")
    try:
        _record_outcome(
            store,
            cycle_id="cyc_ok",
            day=now.date().isoformat(),
            created_at=now - timedelta(minutes=1),
            outcome="executed",
        )
        for index in range(5):
            _record_outcome(
                store,
                cycle_id=f"cyc_old_fail_{index}",
                day=now.date().isoformat(),
                created_at=now - timedelta(minutes=30 + index),
                outcome="provider_error",
            )
        available = runtime._provider_available()
    finally:
        store.close()

    assert available is True


def test_the_breaker_allows_a_first_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no history the channel must be usable."""
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    runtime = _runtime(tmp_path, monkeypatch, now)

    assert runtime._provider_available() is True
