"""Cryptographic RiskDecision binding service (M08-W07).

The one service that persists an approved decision and validates it as
the only executable backend contract. A missing, rejected, expired,
already-consumed, account-mismatched, policy-mismatched,
intent-mismatched, snapshot-mismatched, or quantity-exceeding decision
is rejected by the backend before any network submit (REQ-RISK-010,
AC-M08-W07-02). Neither the AI path nor the manual paper path can
construct an executable approval boolean: the backend validates against
the persisted record, never against a caller-supplied flag
(AC-M08-W07-03).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from alphabrief_risk.decision_store import (
    RiskDecisionRecord,
    RiskDecisionStore,
)


def hash_inputs(
    *,
    symbol: str,
    units: Decimal,
    price: Decimal | None,
) -> str:
    """One deterministic hash of the executable order inputs.

    Both the persisting path and the executing backend compute this hash
    from the same three components (symbol, units, price), so a
    post-approval change of any of them invalidates the decision. The
    instrument version and market snapshot hash are bound separately on
    the persisted record for audit and cross-checked when supplied.
    """
    payload = "|".join(
        [
            symbol.strip().upper(),
            str(units),
            "" if price is None else str(price),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_policy(policy_version: str) -> str:
    """One deterministic hash of the policy version authority."""
    return hashlib.sha256(policy_version.encode("utf-8")).hexdigest()


class DecisionValidation(BaseModel):
    """One deterministic validation verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    kind: str
    detail: str


class DecisionBindingError(RuntimeError):
    """A classified fail-closed decision-binding failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"decision binding failed ({kind}): {detail}")


class DecisionBindingService:
    """Persists decisions and validates them as the execution contract."""

    def __init__(
        self,
        store: RiskDecisionStore,
        *,
        default_expiry_seconds: int = 300,
        clock: Any = None,
    ) -> None:
        self._store = store
        self._default_expiry_seconds = default_expiry_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def persist_decision(
        self,
        decision_id: str,
        *,
        intent_id: str,
        account_id: str,
        approved: bool,
        reason: str,
        max_quantity: Decimal | None,
        risk_tags: tuple[str, ...],
        policy_hash: str,
        inputs_hash: str,
        snapshot_hash: str | None,
        rule_results: str,
        source_ids: tuple[str, ...],
        context_freshness: bool,
        expiry_at: datetime | None = None,
    ) -> RiskDecisionRecord:
        """Persist one immutable decision record before execution."""
        now = self._clock()
        record = RiskDecisionRecord(
            decision_id=decision_id,
            intent_id=intent_id,
            account_id=account_id,
            approved=approved,
            reason=reason,
            max_quantity=max_quantity,
            risk_tags=risk_tags,
            policy_hash=policy_hash,
            inputs_hash=inputs_hash,
            snapshot_hash=snapshot_hash,
            rule_results=rule_results,
            source_ids=source_ids,
            context_freshness=context_freshness,
            created_at=now,
            expiry_at=expiry_at
            or (now + timedelta(seconds=self._default_expiry_seconds)),
        )
        self._store.persist(record)
        # Return the authoritative stored row: a duplicate persist of the
        # same decision_id keeps the first immutable record.
        stored = self._store.get(decision_id)
        assert stored is not None
        return stored

    def validate_before_submit(
        self,
        decision_id: str,
        *,
        expected_intent_id: str,
        expected_account_id: str,
        expected_policy_hash: str,
        expected_inputs_hash: str,
        expected_snapshot_hash: str | None,
        quantity: Decimal,
        now: datetime | None = None,
    ) -> DecisionValidation:
        """Validate the persisted decision as the only executable contract.

        Every defect is classified; a valid decision is consumed exactly
        once so it can never be executed twice.
        """
        observed_at = now or self._clock()
        record = self._store.get(decision_id)
        if record is None:
            return DecisionValidation(
                valid=False, kind="missing", detail="decision is not persisted"
            )
        if not record.approved:
            return DecisionValidation(
                valid=False, kind="rejected", detail="decision is not approved"
            )
        if record.is_expired(observed_at):
            return DecisionValidation(
                valid=False, kind="expired", detail="decision has expired"
            )
        if record.consumed:
            return DecisionValidation(
                valid=False,
                kind="consumed",
                detail="decision was already executed",
            )
        if record.account_id != expected_account_id:
            return DecisionValidation(
                valid=False,
                kind="account_mismatch",
                detail=(
                    f"decision account {record.account_id!r} does not match "
                    f"{expected_account_id!r}"
                ),
            )
        if record.policy_hash != expected_policy_hash:
            return DecisionValidation(
                valid=False,
                kind="policy_mismatch",
                detail="policy hash does not match the decision",
            )
        if record.intent_id != expected_intent_id:
            return DecisionValidation(
                valid=False,
                kind="intent_mismatch",
                detail="intent id does not match the decision",
            )
        if record.inputs_hash != expected_inputs_hash:
            return DecisionValidation(
                valid=False,
                kind="inputs_mismatch",
                detail="executable inputs no longer match the decision",
            )
        if (
            expected_snapshot_hash is not None
            and record.snapshot_hash != expected_snapshot_hash
        ):
            return DecisionValidation(
                valid=False,
                kind="snapshot_mismatch",
                detail="market snapshot no longer matches the decision",
            )
        if record.max_quantity is not None and quantity > record.max_quantity:
            return DecisionValidation(
                valid=False,
                kind="quantity_exceeds",
                detail=(
                    f"quantity {quantity} exceeds decision max_quantity "
                    f"{record.max_quantity}"
                ),
            )
        if not record.context_freshness:
            return DecisionValidation(
                valid=False,
                kind="stale_context",
                detail="decision context was not fresh at approval",
            )
        self._store.consume(decision_id, owner="decision-binding")
        return DecisionValidation(
            valid=True, kind="valid", detail="decision is the executable contract"
        )


__all__ = [
    "DecisionBindingError",
    "DecisionBindingService",
    "DecisionValidation",
    "hash_inputs",
    "hash_policy",
]
