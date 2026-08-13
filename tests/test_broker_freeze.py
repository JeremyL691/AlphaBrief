"""M07-W05: evidence-backed freeze and unfreeze policy.

Covers:
- every blocking diff, unresolved transaction gap, stale remote
  snapshot, failed resync, or corrupt projection raises one deduplicated
  durable freeze before another new-exposure submit (AC-M07-W05-01);
- unfreeze requires a fresh successful full sync, zero blocking diffs,
  matching cursor and projection hashes, resolved alerts, and an
  immutable reason and evidence record (AC-M07-W05-02);
- repeated freeze and unfreeze commands are idempotent and no API, CLI,
  scheduler, model, or fallback path can clear a freeze by omission or
  confirmation prompt (AC-M07-W05-03).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alphabrief_execution.broker.oanda.freeze_policy import (
    ExposureFreezeStore,
    FreezeActiveError,
    FreezeReason,
    UnfreezeDeniedError,
)

ACCOUNT = "101-004-1234567-001"


def _store(tmp_path: Path) -> ExposureFreezeStore:
    return ExposureFreezeStore(db_path=tmp_path / "freeze.db")


def _freeze_all(
    store: ExposureFreezeStore, account: str = ACCOUNT
) -> dict[str, str]:
    """One freeze per alarm class; returns reason -> freeze_id."""
    ids: dict[str, str] = {}
    alarms: list[tuple[FreezeReason, str]] = [
        ("blocking_diff", "balance shortfall beyond tolerance"),
        ("unresolved_gap", "transaction gap 103-107 open after ceiling"),
        ("stale_snapshot", "remote snapshot older than 5 minutes"),
        ("resync_failed", "full sync failed after 3 attempts"),
        ("corrupt_projection", "projection hash mismatch on rebuild"),
        ("cursor_failure", "broker cursor behind local cursor"),
    ]
    for reason, detail in alarms:
        ids[reason] = store.freeze_new_exposure(
            account, reason=reason, detail=detail
        )
    return ids


# ---------------------------------------------------------------------------
# AC-M07-W05-01: one deduplicated durable freeze before new-exposure submit
# ---------------------------------------------------------------------------


def test_every_alarm_class_raises_a_durable_freeze(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        ids = _freeze_all(store)
        assert len(ids) == 6
        assert len(store.active_freezes(ACCOUNT)) == 6
        # Every freeze blocks a new-exposure submit.
        with pytest.raises(FreezeActiveError):
            store.ensure_new_exposure_allowed(ACCOUNT)
    finally:
        store.close()


def test_repeated_alarms_deduplicate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        first = store.freeze_new_exposure(
            ACCOUNT, reason="blocking_diff", detail="balance shortfall"
        )
        second = store.freeze_new_exposure(
            ACCOUNT, reason="blocking_diff", detail="balance shortfall"
        )
        assert second == first
        assert len(store.active_freezes(ACCOUNT)) == 1
        # A different detail is a distinct freeze, still durable.
        third = store.freeze_new_exposure(
            ACCOUNT, reason="blocking_diff", detail="margin shortfall"
        )
        assert third != first
        assert len(store.active_freezes(ACCOUNT)) == 2
    finally:
        store.close()


def test_freeze_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "freeze.db"
    store = ExposureFreezeStore(db_path=path)
    try:
        store.freeze_new_exposure(
            ACCOUNT, reason="cursor_failure", detail="cursor behind"
        )
    finally:
        store.close()

    reopened = ExposureFreezeStore(db_path=path)
    try:
        assert len(reopened.active_freezes(ACCOUNT)) == 1
        with pytest.raises(FreezeActiveError):
            reopened.ensure_new_exposure_allowed(ACCOUNT)
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# AC-M07-W05-02: evidence-backed unfreeze only
# ---------------------------------------------------------------------------


def test_unfreeze_denied_when_any_check_fails(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        _freeze_all(store)
        cases: list[dict[str, Any]] = [
            dict(
                fresh_sync_ok=False,
                blocking_diffs=0,
                cursor_match=True,
                projection_hash_match=True,
                resolved_alerts=True,
            ),
            dict(
                fresh_sync_ok=True,
                blocking_diffs=1,
                cursor_match=True,
                projection_hash_match=True,
                resolved_alerts=True,
            ),
            dict(
                fresh_sync_ok=True,
                blocking_diffs=0,
                cursor_match=False,
                projection_hash_match=True,
                resolved_alerts=True,
            ),
            dict(
                fresh_sync_ok=True,
                blocking_diffs=0,
                cursor_match=True,
                projection_hash_match=False,
                resolved_alerts=True,
            ),
            dict(
                fresh_sync_ok=True,
                blocking_diffs=0,
                cursor_match=True,
                projection_hash_match=True,
                resolved_alerts=False,
            ),
        ]
        for case in cases:
            with pytest.raises(UnfreezeDeniedError) as excinfo:
                store.unfreeze(ACCOUNT, reason="resync complete", **case)
            assert excinfo.value.failing
        # Nothing was unfrozen by the denied attempts.
        assert len(store.active_freezes(ACCOUNT)) == 6
        assert store.unfreeze_history(ACCOUNT) == []
    finally:
        store.close()


def test_unfreeze_requires_all_checks_and_writes_immutable_evidence(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    try:
        ids = _freeze_all(store)
        store.unfreeze(
            ACCOUNT,
            fresh_sync_ok=True,
            blocking_diffs=0,
            cursor_match=True,
            projection_hash_match=True,
            resolved_alerts=True,
            reason="full resync verified",
        )
        assert store.active_freezes(ACCOUNT) == []
        # Immutable evidence: every unfreeze carries the full policy
        # snapshot, never just a confirmation.
        history = store.unfreeze_history(ACCOUNT)
        assert len(history) == 6
        assert all(entry["fresh_sync_ok"] for entry in history)
        assert all(entry["blocking_diffs"] == 0 for entry in history)
        assert all(entry["projection_hash_match"] for entry in history)
        assert all(entry["reason"] == "full resync verified" for entry in history)
        assert {entry["freeze_id"] for entry in history} == set(ids.values())
        # New exposure is allowed again.
        store.ensure_new_exposure_allowed(ACCOUNT)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC-M07-W05-03: idempotent, and no path clears by omission
# ---------------------------------------------------------------------------


def test_repeated_unfreeze_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        _freeze_all(store)
        store.unfreeze(
            ACCOUNT,
            fresh_sync_ok=True,
            blocking_diffs=0,
            cursor_match=True,
            projection_hash_match=True,
            resolved_alerts=True,
            reason="verified",
        )
        history_before = len(store.unfreeze_history(ACCOUNT))
        # A repeated unfreeze with nothing frozen is a silent no-op.
        store.unfreeze(
            ACCOUNT,
            fresh_sync_ok=True,
            blocking_diffs=0,
            cursor_match=True,
            projection_hash_match=True,
            resolved_alerts=True,
            reason="verified again",
        )
        assert len(store.unfreeze_history(ACCOUNT)) == history_before
    finally:
        store.close()


def test_no_path_clears_a_freeze_by_omission(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        _freeze_all(store)
        # Every unfreeze parameter defaults to the denying value: an
        # omitted check can never clear a freeze.
        with pytest.raises(UnfreezeDeniedError):
            store.unfreeze(ACCOUNT, reason="omitted")
        assert len(store.active_freezes(ACCOUNT)) == 6
        # There is no clear, dismiss, ignore, or confirm API at all.
        for name in (
            "clear",
            "dismiss",
            "ignore",
            "confirm_unfreeze",
            "acknowledge",
        ):
            assert not hasattr(store, name)
        # The freeze blocks new exposure until real evidence exists.
        with pytest.raises(FreezeActiveError):
            store.ensure_new_exposure_allowed(ACCOUNT)
    finally:
        store.close()


def test_freeze_reason_and_evidence_are_recorded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        freeze_id = store.freeze_new_exposure(
            ACCOUNT,
            reason="resync_failed",
            detail="sync failed after ceiling",
            evidence_refs=("ledger:r-1", "cursor:c-1"),
        )
        active = store.active_freezes(ACCOUNT)
        assert active[0]["freeze_id"] == freeze_id
        assert active[0]["reason"] == "resync_failed"
        assert active[0]["evidence_refs"] == ("ledger:r-1", "cursor:c-1")
    finally:
        store.close()
