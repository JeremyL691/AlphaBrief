"""M06-W03: order and dependent-order transition facts.

Covers:
- every documented transition fixture produces immutable ordered facts
  with broker transaction IDs, related IDs, UTC times, quantities,
  prices, reasons, financing, and correlation IDs (AC-M06-W03-01);
- immediate fill, pending, partial fill, cancel, reject, expire,
  reissue, reduce, close, and dependent-order transitions update
  projections deterministically without impossible state jumps
  (AC-M06-W03-02);
- duplicate, out-of-order, malformed, or conflicting facts are
  idempotently ignored or quarantined and never mutate a terminal fact
  or fabricate a fill (AC-M06-W03-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_execution.broker.oanda.transition_store import OrderTransitionStore
from alphabrief_execution.broker.oanda.transitions import (
    OrderTransition,
    apply_transition,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _transition(
    transition_id: str,
    kind: str,
    order_id: str = "order-1",
    *,
    quantity: str = "1000",
    price: str | None = "1.10500",
    related_id: str | None = None,
    after_state: str | None = None,
    occurred_at: datetime = NOW,
) -> OrderTransition:
    return OrderTransition(
        transition_id=transition_id,
        order_id=order_id,
        related_id=related_id,
        kind=kind,  # type: ignore[arg-type]
        before_state=None,
        after_state=after_state,  # type: ignore[arg-type]
        quantity=Decimal(quantity),
        price=Decimal(price) if price is not None else None,
        reason=f"fixture {kind}",
        financing=Decimal("0"),
        correlation_id=f"corr-{transition_id}",
        occurred_at=occurred_at,
    )


# ---------------------------------------------------------------------------
# AC-M06-W03-01: immutable typed facts
# ---------------------------------------------------------------------------


def test_transition_fixture_carries_all_fields() -> None:
    transition = _transition("tx-1", "FILLED", related_id="parent-1")
    assert transition.transition_id == "tx-1"
    assert transition.order_id == "order-1"
    assert transition.related_id == "parent-1"
    assert transition.kind == "FILLED"
    assert transition.quantity == Decimal("1000")
    assert transition.price == Decimal("1.10500")
    assert transition.reason == "fixture FILLED"
    assert transition.financing == Decimal("0")
    assert transition.correlation_id == "corr-tx-1"
    assert transition.occurred_at.tzinfo is not None


def test_float_fields_are_rejected() -> None:
    with pytest.raises(ValueError):
        OrderTransition(
            transition_id="tx-x",
            order_id="order-1",
            kind="FILLED",
            before_state=None,
            after_state=None,
            quantity=1.5,  # type: ignore[arg-type]
            price=None,
            reason="",
            financing=Decimal("0"),
            correlation_id="c",
            occurred_at=NOW,
        )


def test_store_persists_transitions_immutably(tmp_path: Path) -> None:
    store = OrderTransitionStore(db_path=tmp_path / "tx.db")
    try:
        store.record(_transition("tx-1", "CREATED"))
        store.record(_transition("tx-2", "FILLED"))
        assert store.transition_count() == 2
        projection = store.projection("order-1")
        assert projection is not None
        assert projection.state == "FILLED"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC-M06-W03-02: deterministic projections without impossible jumps
# ---------------------------------------------------------------------------


def test_full_lifecycle_projection(tmp_path: Path) -> None:
    store = OrderTransitionStore(db_path=tmp_path / "tx.db")
    try:
        store.record(_transition("tx-1", "CREATED"))
        store.record(_transition("tx-2", "PARTIAL_FILL", quantity="400"))
        projection = store.projection("order-1")
        assert projection is not None
        assert projection.state == "PARTIALLY_FILLED"
        assert projection.open_quantity == Decimal("600")
        assert projection.filled_quantity == Decimal("400")

        store.record(_transition("tx-3", "FILLED", quantity="600"))
        projection = store.projection("order-1")
        assert projection is not None
        assert projection.state == "FILLED"
        assert projection.open_quantity == Decimal("0")
        assert projection.filled_quantity == Decimal("1000")
    finally:
        store.close()


def test_cancel_reject_expire_projections(tmp_path: Path) -> None:
    for kind in ("CANCELLED", "REJECTED", "EXPIRED"):
        store = OrderTransitionStore(db_path=tmp_path / f"tx-{kind}.db")
        try:
            store.record(_transition("c1", "CREATED", order_id=f"o-{kind}"))
            store.record(_transition("c2", kind, order_id=f"o-{kind}"))
            projection = store.projection(f"o-{kind}")
            assert projection is not None
            assert projection.state == kind
        finally:
            store.close()


def test_reissue_changes_order_id_without_jump(tmp_path: Path) -> None:
    store = OrderTransitionStore(db_path=tmp_path / "tx.db")
    try:
        store.record(_transition("r1", "CREATED"))
        store.record(_transition("r2", "REISSUED", related_id="order-2"))
        projection = store.projection("order-1")
        assert projection is not None
        assert projection.state == "PENDING"
        # The projection identity is stable; the reissued broker order id
        # is recorded on the transition.
        assert projection.order_id == "order-1"
    finally:
        store.close()


def test_reduce_and_close(tmp_path: Path) -> None:
    store = OrderTransitionStore(db_path=tmp_path / "tx.db")
    try:
        store.record(_transition("d1", "CREATED", quantity="1000"))
        store.record(_transition("d2", "FILLED", quantity="1000"))
        store.record(_transition("d3", "REDUCED", quantity="300"))
        store.record(_transition("d4", "CLOSED", quantity="700"))
        projection = store.projection("order-1")
        assert projection is not None
        assert projection.state == "CLOSED"
        assert projection.open_quantity == Decimal("0")
    finally:
        store.close()


def test_dependent_order_transitions_do_not_mutate_parent(tmp_path: Path) -> None:
    store = OrderTransitionStore(db_path=tmp_path / "tx.db")
    try:
        store.record(_transition("e1", "CREATED"))
        store.record(
            _transition(
                "e2",
                "DEPENDENT_CREATED",
                related_id="dependent-tp-1",
            )
        )
        projection = store.projection("order-1")
        assert projection is not None
        assert projection.state == "PENDING"
    finally:
        store.close()


def test_impossible_jump_is_rejected() -> None:
    created = _transition("t1", "CREATED")
    projection, _ = apply_transition(None, created)
    # FILLED -> PENDING is an impossible jump.
    filled = _transition("t2", "FILLED")
    projection, _ = apply_transition(projection, filled)
    rejected = _transition("t3", "CREATED")
    updated, rejection = apply_transition(projection, rejected)
    assert rejection is not None
    assert "terminal state" in rejection.reason
    assert updated is not None
    assert updated.state == "FILLED"


def test_reduce_without_prior_order_is_rejected() -> None:
    updated, rejection = apply_transition(
        None, _transition("t9", "REDUCED")
    )
    assert rejection is not None
    assert "without a prior order" in rejection.reason


# ---------------------------------------------------------------------------
# AC-M06-W03-03: duplicates, out-of-order, malformed, conflicting
# ---------------------------------------------------------------------------


def test_duplicate_transition_id_is_ignored_idempotently(tmp_path: Path) -> None:
    store = OrderTransitionStore(db_path=tmp_path / "tx.db")
    try:
        store.record(_transition("dup-1", "CREATED"))
        summary = store.record(_transition("dup-1", "FILLED"))
        assert summary.applied is False
        assert store.transition_count() == 1
        projection = store.projection("order-1")
        assert projection is not None
        assert projection.state == "PENDING"
    finally:
        store.close()


def test_conflicting_transition_is_quarantined(tmp_path: Path) -> None:
    store = OrderTransitionStore(db_path=tmp_path / "tx.db")
    try:
        store.record(_transition("q1", "FILLED"))
        # A later transition trying to mutate a terminal projection.
        summary = store.record(_transition("q2", "PARTIAL_FILL"))
        assert summary.applied is False
        assert summary.rejected_reason is not None
        rejections = store.rejections()
        assert any(r["transition_id"] == "q2" for r in rejections)
        projection = store.projection("order-1")
        assert projection is not None
        assert projection.state == "FILLED"
        assert projection.filled_quantity == Decimal("1000")
    finally:
        store.close()


def test_malformed_transition_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        OrderTransition(
            transition_id="m1",
            order_id="order-1",
            kind="BOGUS",  # type: ignore[arg-type]
            before_state=None,
            after_state=None,
            quantity=Decimal("1"),
            price=None,
            reason="",
            financing=Decimal("0"),
            correlation_id="c",
            occurred_at=NOW,
        )


def test_after_state_conflict_is_rejected() -> None:
    projection, _ = apply_transition(None, _transition("a1", "CREATED"))
    conflicting = _transition("a2", "FILLED", after_state="PENDING")
    updated, rejection = apply_transition(projection, conflicting)
    assert rejection is not None
    assert "after_state conflicts" in rejection.reason
    assert updated is not None
    assert updated.state == "PENDING"
