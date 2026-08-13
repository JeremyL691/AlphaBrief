"""M11-W02: one scheduler leader via a renewable persisted lease.

Covers AC-M11-W02-01/02: two scheduler processes competing for the same
store produce exactly one active leader and one non-writing follower;
lease expiry or loss prevents the former leader from continuing before a
new leader takes over.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alphabrief_trader.scheduler_leader import SchedulerLeaderLease

_T0 = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, start: datetime = _T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def lease(tmp_path: Path, clock: _Clock) -> Iterator[SchedulerLeaderLease]:
    store = SchedulerLeaderLease(db_path=tmp_path / "lease.db", clock=clock)
    try:
        yield store
    finally:
        store.close()


class TestSingleLeader:
    def test_two_competitors_produce_one_leader(
        self, lease: SchedulerLeaderLease
    ) -> None:
        assert lease.acquire("scheduler-a", ttl_seconds=60) is True
        # A second process cannot take over while the lease is active.
        assert lease.acquire("scheduler-b", ttl_seconds=60) is False
        assert lease.is_leader("scheduler-a") is True
        assert lease.is_leader("scheduler-b") is False
        leader = lease.leader()
        assert leader is not None
        assert leader["holder_id"] == "scheduler-a"

    def test_leader_can_renew_and_keep_leadership(
        self, lease: SchedulerLeaderLease, clock: _Clock
    ) -> None:
        assert lease.acquire("scheduler-a", ttl_seconds=60) is True
        clock.now += timedelta(seconds=30)
        assert lease.renew("scheduler-a", ttl_seconds=60) is True
        assert lease.is_leader("scheduler-a") is True
        # Renewal extends the expiry: still leader later.
        clock.now += timedelta(seconds=30)
        assert lease.is_leader("scheduler-a") is True

    def test_expired_lease_allows_takeover(
        self, lease: SchedulerLeaderLease, clock: _Clock
    ) -> None:
        assert lease.acquire("scheduler-a", ttl_seconds=60) is True
        clock.now += timedelta(seconds=61)
        # The former leader's lease is expired.
        assert lease.is_leader("scheduler-a") is False
        assert lease.renew("scheduler-a", ttl_seconds=60) is False
        # A new leader takes over after expiry.
        assert lease.acquire("scheduler-b", ttl_seconds=60) is True
        assert lease.is_leader("scheduler-b") is True
        assert lease.is_leader("scheduler-a") is False

    def test_non_holder_cannot_renew(
        self, lease: SchedulerLeaderLease
    ) -> None:
        assert lease.acquire("scheduler-a", ttl_seconds=60) is True
        assert lease.renew("scheduler-b", ttl_seconds=60) is False
        assert lease.is_leader("scheduler-a") is True

    def test_release_hands_leadership_over(
        self, lease: SchedulerLeaderLease
    ) -> None:
        assert lease.acquire("scheduler-a", ttl_seconds=60) is True
        assert lease.release("scheduler-a") is True
        assert lease.is_leader("scheduler-a") is False
        assert lease.acquire("scheduler-b", ttl_seconds=60) is True

    def test_foreign_release_rejected(
        self, lease: SchedulerLeaderLease
    ) -> None:
        assert lease.acquire("scheduler-a", ttl_seconds=60) is True
        assert lease.release("scheduler-b") is False
        assert lease.is_leader("scheduler-a") is True

    def test_validation_rejects_blank_holder(
        self, lease: SchedulerLeaderLease
    ) -> None:
        with pytest.raises(ValueError):
            lease.acquire("   ", ttl_seconds=60)
        with pytest.raises(ValueError):
            lease.acquire("a", ttl_seconds=0)

    def test_lease_survives_store_restart(
        self, tmp_path: Path, clock: _Clock
    ) -> None:
        first = SchedulerLeaderLease(db_path=tmp_path / "lease.db", clock=clock)
        try:
            assert first.acquire("scheduler-a", ttl_seconds=60) is True
        finally:
            first.close()

        second = SchedulerLeaderLease(db_path=tmp_path / "lease.db", clock=clock)
        try:
            assert second.is_leader("scheduler-a") is True
            assert second.acquire("scheduler-b", ttl_seconds=60) is False
            assert second.renew("scheduler-a", ttl_seconds=60) is True
        finally:
            second.close()
