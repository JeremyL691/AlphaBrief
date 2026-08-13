"""M08-W07: decision-binding service and executable contract.

Missing, rejected, expired, already consumed, account-mismatched,
policy-mismatched, intent-mismatched, snapshot-mismatched, or
quantity-exceeding decisions are rejected by the backend before network
submit (AC-M08-W07-02); AI and manual paper paths invoke the same
binding service and no caller can construct an executable approval
boolean or mutate inputs after approval (AC-M08-W07-03).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alphabrief_risk.decision_binding import (
    DecisionBindingService,
    DecisionValidation,
    hash_inputs,
    hash_policy,
)
from alphabrief_risk.decision_store import RiskDecisionStore

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
ACCOUNT = "101-004-1234567-001"


def _service(tmp_path: Path) -> DecisionBindingService:
    return DecisionBindingService(
        RiskDecisionStore(db_path=tmp_path / "decisions.db"),
        clock=lambda: NOW,
    )


def _persist(
    service: DecisionBindingService,
    *,
    decision_id: str = "risk-1",
    intent_id: str = "intent-1",
    account_id: str = ACCOUNT,
    approved: bool = True,
    max_quantity: Decimal | None = Decimal("10"),
    inputs_hash: str | None = None,
    snapshot_hash: str | None = "sha256:snapshot",
    context_freshness: bool = True,
    expiry_at: datetime | None = None,
) -> None:
    service.persist_decision(
        decision_id,
        intent_id=intent_id,
        account_id=account_id,
        approved=approved,
        reason="approved",
        max_quantity=max_quantity,
        risk_tags=("approved",),
        policy_hash=hash_policy("2026-08-13.1"),
        inputs_hash=inputs_hash
        or hash_inputs(symbol="EUR_USD", units=Decimal("1"), price=None),
        snapshot_hash=snapshot_hash,
        rule_results="rule_a=pass",
        source_ids=(f"account:{account_id}",),
        context_freshness=context_freshness,
        expiry_at=expiry_at,
    )


def _validate(
    service: DecisionBindingService,
    decision_id: str = "risk-1",
    *,
    intent_id: str = "intent-1",
    account_id: str = ACCOUNT,
    quantity: Decimal = Decimal("1"),
) -> DecisionValidation:
    return service.validate_before_submit(
        decision_id,
        expected_intent_id=intent_id,
        expected_account_id=account_id,
        expected_policy_hash=hash_policy("2026-08-13.1"),
        expected_inputs_hash=hash_inputs(
            symbol="EUR_USD", units=quantity, price=None
        ),
        expected_snapshot_hash=None,
        quantity=quantity,
        now=NOW,
    )


def test_valid_persisted_decision_is_executable_and_consumed(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _persist(service)
    validation = _validate(service)
    assert validation.valid is True
    assert validation.kind == "valid"
    # A valid decision is consumed exactly once: re-execution is refused.
    validation = _validate(service)
    assert validation.valid is False
    assert validation.kind == "consumed"


def test_missing_decision_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    validation = _validate(service)
    assert validation.valid is False
    assert validation.kind == "missing"


def test_rejected_decision_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service, approved=False)
    validation = _validate(service)
    assert validation.valid is False
    assert validation.kind == "rejected"


def test_expired_decision_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service, expiry_at=NOW - timedelta(seconds=1))
    validation = _validate(service)
    assert validation.valid is False
    assert validation.kind == "expired"


def test_account_mismatch_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service)
    validation = _validate(service, account_id="other-account")
    assert validation.valid is False
    assert validation.kind == "account_mismatch"


def test_policy_mismatch_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service)
    validation = service.validate_before_submit(
        "risk-1",
        expected_intent_id="intent-1",
        expected_account_id=ACCOUNT,
        expected_policy_hash=hash_policy("2026-08-13.2"),
        expected_inputs_hash=hash_inputs(
            symbol="EUR_USD", units=Decimal("1"), price=None
        ),
        expected_snapshot_hash=None,
        quantity=Decimal("1"),
        now=NOW,
    )
    assert validation.valid is False
    assert validation.kind == "policy_mismatch"


def test_intent_mismatch_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service)
    validation = _validate(service, intent_id="other-intent")
    assert validation.valid is False
    assert validation.kind == "intent_mismatch"


def test_inputs_mutation_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service)
    # A post-approval quantity change produces a different inputs hash.
    validation = _validate(service, quantity=Decimal("2"))
    assert validation.valid is False
    assert validation.kind == "inputs_mismatch"


def test_snapshot_mismatch_rejected_when_supplied(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service)
    validation = service.validate_before_submit(
        "risk-1",
        expected_intent_id="intent-1",
        expected_account_id=ACCOUNT,
        expected_policy_hash=hash_policy("2026-08-13.1"),
        expected_inputs_hash=hash_inputs(
            symbol="EUR_USD", units=Decimal("1"), price=None
        ),
        expected_snapshot_hash="sha256:other-snapshot",
        quantity=Decimal("1"),
        now=NOW,
    )
    assert validation.valid is False
    assert validation.kind == "snapshot_mismatch"


def test_quantity_exceeding_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    # The decision approves units=11 but caps quantity at 10.
    _persist(
        service,
        max_quantity=Decimal("10"),
        inputs_hash=hash_inputs(
            symbol="EUR_USD", units=Decimal("11"), price=None
        ),
    )
    validation = _validate(service, quantity=Decimal("11"))
    assert validation.valid is False
    assert validation.kind == "quantity_exceeds"


def test_stale_context_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service, context_freshness=False)
    validation = _validate(service)
    assert validation.valid is False
    assert validation.kind == "stale_context"


def test_duplicate_persist_keeps_first_record(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _persist(service)
    # A retry with mutated inputs cannot overwrite the first record.
    _persist(service, inputs_hash=hash_inputs(
        symbol="EUR_USD", units=Decimal("99"), price=None
    ))
    validation = _validate(service)
    assert validation.valid is True  # first record (units=1) governs
