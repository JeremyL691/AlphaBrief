"""M07-W01: idempotency identities in the local order ledger.

Covers:
- one deterministic cycle+intent identity reserves at most one submit
  identity under sequential, timeout, and restart replays
  (AC-M07-W01-01);
- identity collision, mismatched payload hash, stale owner, ambiguous
  in-flight state, and missing approved decision freeze submission
  without overwrite, fallback, or user question (AC-M07-W01-03).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from alphabrief_execution.broker.oanda.order_ledger import (
    LedgerTransitionError,
    OrderLedger,
    ReservationOutcome,
)

CYCLE = "cycle-2026-08-13"
INTENT = "intent-42"
OWNER = "daily-runner"
PAYLOAD = "sha256:abc123"


def _ledger(tmp_path: Path, name: str = "ledger.db") -> OrderLedger:
    return OrderLedger(db_path=tmp_path / name)


def _reserve(
    ledger: OrderLedger,
    *,
    cycle: str = CYCLE,
    intent: str = INTENT,
    decision: str = "risk-1",
    payload: str = PAYLOAD,
    owner: str = OWNER,
) -> ReservationOutcome:
    return ledger.reserve(
        cycle_id=cycle,
        intent_id=intent,
        decision_id=decision,
        payload_hash=payload,
        owner=owner,
    )


# ---------------------------------------------------------------------------
# AC-M07-W01-01: at most one submit identity under every replay
# ---------------------------------------------------------------------------


def test_100_sequential_replays_reserve_one_identity(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        first = _reserve(ledger)
        assert first.reused is False
        assert first.status == "RESERVED"
        for _ in range(99):
            replay = _reserve(ledger)
            assert replay.submit_id == first.submit_id
            assert replay.reused is True
        assert ledger.reservation_count() == 1
        # Exactly one immutable reservation event exists.
        events = ledger.events(first.submit_id)
        assert [e["kind"] for e in events] == ["RESERVED"]
    finally:
        ledger.close()


def test_reservation_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = OrderLedger(db_path=path)
    try:
        reserved = _reserve(ledger)
        ledger.bind_decision(
            reserved.submit_id,
            decision_id="risk-1",
            payload_hash=PAYLOAD,
            owner=OWNER,
        )
        ledger.record_submit_attempt(
            reserved.submit_id, payload_hash=PAYLOAD, owner=OWNER
        )
    finally:
        ledger.close()

    # Restart: the same identity and state are preserved.
    reopened = OrderLedger(db_path=path)
    try:
        replay = _reserve(reopened)
        assert replay.reused is True
        assert replay.submit_id == f"{CYCLE}:{INTENT}"
        assert replay.status == "SUBMITTED"
        assert reopened.status(replay.submit_id) == "SUBMITTED"
    finally:
        reopened.close()


def test_timeout_replay_preserves_in_flight_state(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        reserved = _reserve(ledger)
        submit_id = reserved.submit_id
        ledger.bind_decision(
            submit_id, decision_id="risk-1", payload_hash=PAYLOAD, owner=OWNER
        )
        ledger.record_submit_attempt(
            submit_id, payload_hash=PAYLOAD, owner=OWNER
        )
        # The broker timed out after submit: the state stays SUBMITTED.
        assert ledger.status(submit_id) == "SUBMITTED"
        events_before = ledger.events(submit_id)
        with pytest.raises(LedgerTransitionError) as excinfo:
            ledger.record_submit_attempt(
                submit_id, payload_hash=PAYLOAD, owner=OWNER
            )
        assert excinfo.value.kind == "in_flight_ambiguous"
        # Nothing was overwritten or duplicated.
        assert ledger.status(submit_id) == "SUBMITTED"
        assert ledger.events(submit_id) == events_before
    finally:
        ledger.close()


# ---------------------------------------------------------------------------
# AC-M07-W01-03: collision and misuse freeze without overwrite
# ---------------------------------------------------------------------------


def test_identity_collision_freezes_without_overwrite(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        _reserve(ledger, decision="risk-1")
        with pytest.raises(LedgerTransitionError) as excinfo:
            _reserve(ledger, decision="risk-2")
        assert excinfo.value.kind == "identity_collision"
        reservation = ledger.reservation(f"{CYCLE}:{INTENT}")
        assert reservation is not None
        # The original decision was never overwritten.
        assert reservation["decision_id"] == "risk-1"
    finally:
        ledger.close()


def test_payload_hash_mismatch_freezes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        reserved = _reserve(ledger, payload="sha256:abc")
        submit_id = reserved.submit_id
        with pytest.raises(LedgerTransitionError) as excinfo:
            ledger.bind_decision(
                submit_id, decision_id="risk-1", payload_hash="sha256:evil", owner=OWNER
            )
        assert excinfo.value.kind == "payload_mismatch"
        with pytest.raises(LedgerTransitionError) as excinfo:
            ledger.record_submit_attempt(
                submit_id, payload_hash="sha256:evil", owner=OWNER
            )
        assert excinfo.value.kind == "payload_mismatch"
        assert ledger.status(submit_id) == "RESERVED"
    finally:
        ledger.close()


def test_stale_owner_freezes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        reserved = _reserve(ledger, owner="runner-a")
        submit_id = reserved.submit_id
        with pytest.raises(LedgerTransitionError) as excinfo:
            ledger.bind_decision(
                submit_id, decision_id="risk-1", payload_hash=PAYLOAD, owner="runner-b"
            )
        assert excinfo.value.kind == "stale_owner"
        with pytest.raises(LedgerTransitionError) as excinfo:
            ledger.record_broker_result(
                submit_id,
                broker_order_id="1",
                state="FILLED",
                transaction_id="10",
                owner="runner-b",
            )
        assert excinfo.value.kind == "stale_owner"
    finally:
        ledger.close()


def test_submit_without_approved_decision_freezes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        reserved = _reserve(ledger)
        submit_id = reserved.submit_id
        with pytest.raises(LedgerTransitionError) as excinfo:
            ledger.record_submit_attempt(
                submit_id, payload_hash=PAYLOAD, owner=OWNER
            )
        assert excinfo.value.kind == "missing_decision"
        assert ledger.status(submit_id) == "RESERVED"
    finally:
        ledger.close()


def test_frozen_reservation_never_transitions(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        reserved = _reserve(ledger)
        submit_id = reserved.submit_id
        ledger.freeze(submit_id, reason="unresolved outcome", owner=OWNER)
        assert ledger.status(submit_id) == "FROZEN"
        operations: list[Callable[[], object]] = [
            lambda: ledger.bind_decision(
                submit_id,
                decision_id="risk-1",
                payload_hash=PAYLOAD,
                owner=OWNER,
            ),
            lambda: ledger.record_submit_attempt(
                submit_id, payload_hash=PAYLOAD, owner=OWNER
            ),
            lambda: ledger.record_broker_result(
                submit_id,
                broker_order_id="1",
                state="FILLED",
                transaction_id="10",
                owner=OWNER,
            ),
            lambda: ledger.freeze(submit_id, reason="again", owner=OWNER),
        ]
        for operation in operations:
            with pytest.raises(LedgerTransitionError) as excinfo:
                operation()
            assert excinfo.value.kind == "state_conflict"
        assert ledger.status(submit_id) == "FROZEN"
    finally:
        ledger.close()


def test_cas_conflict_never_overwrites(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        reserved = _reserve(ledger)
        submit_id = reserved.submit_id
        # Bind twice with the same decision: the second is an idempotent
        # replay, not an overwrite.
        ledger.bind_decision(
            submit_id, decision_id="risk-1", payload_hash=PAYLOAD, owner=OWNER
        )
        ledger.bind_decision(
            submit_id, decision_id="risk-1", payload_hash=PAYLOAD, owner=OWNER
        )
        events = ledger.events(submit_id)
        assert [e["kind"] for e in events] == ["RESERVED", "BIND"]
        assert ledger.status(submit_id) == "BOUND"
    finally:
        ledger.close()
