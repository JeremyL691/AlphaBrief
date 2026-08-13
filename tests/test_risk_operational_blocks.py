"""M08-W06: operational health blocks (AC-M08-W06-01).

Kill switch, open freeze, stale broker, unresolved reconciliation diff,
transaction gap, failed required backup, lost writer lease, and
unhealthy scheduler each block new exposure with a distinct persisted
rule result; missing evidence fails closed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alphabrief_risk.operational_blocks import (
    ALL_CONDITIONS,
    OperationalBlockResult,
    OperationalBlockStore,
    OperationalHealthEvidence,
    blocking_conditions,
    evaluate_operational_blocks,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
ACCOUNT = "101-004-1234567-001"


def _evidence(**overrides: object) -> OperationalHealthEvidence:
    payload: dict[str, object] = {
        "kill_switch_active": False,
        "freeze_open": False,
        "broker_stale": False,
        "reconciliation_diff_unresolved": False,
        "transaction_gap_open": False,
        "backup_failed": False,
        "writer_lease_lost": False,
        "scheduler_unhealthy": False,
        "captured_at": NOW,
        "source_id": "health-1",
    }
    payload.update(overrides)
    return OperationalHealthEvidence.model_validate(payload)


def _evaluate(
    **overrides: object,
) -> dict[str, OperationalBlockResult]:
    results = evaluate_operational_blocks(_evidence(**overrides))
    return {result.condition: result for result in results}


def test_all_healthy_blocks_nothing() -> None:
    rules = _evaluate()
    assert blocking_conditions(tuple(rules.values())) == ()
    assert all(not rule.blocked for rule in rules.values())


def test_every_condition_blocks_with_distinct_result() -> None:
    cases = [
        ("kill_switch", {"kill_switch_active": True}),
        ("freeze", {"freeze_open": True}),
        ("stale_broker", {"broker_stale": True}),
        ("reconciliation_diff", {"reconciliation_diff_unresolved": True}),
        ("transaction_gap", {"transaction_gap_open": True}),
        ("backup_failure", {"backup_failed": True}),
        ("writer_lease", {"writer_lease_lost": True}),
        ("scheduler_health", {"scheduler_unhealthy": True}),
    ]
    for condition, overrides in cases:
        rules = _evaluate(**overrides)
        assert rules[condition].blocked is True
        assert blocking_conditions(tuple(rules.values())) == (condition,)
        # Exactly one condition blocks at a time: distinct results.
        assert sum(rule.blocked for rule in rules.values()) == 1


def test_all_conditions_have_stable_identity() -> None:
    assert ALL_CONDITIONS == (
        "kill_switch",
        "freeze",
        "stale_broker",
        "reconciliation_diff",
        "transaction_gap",
        "backup_failure",
        "writer_lease",
        "scheduler_health",
    )


def test_missing_required_evidence_fails_closed() -> None:
    rules = _evaluate(kill_switch_active=None)
    assert rules["kill_switch"].blocked is True
    assert "missing" in rules["kill_switch"].detail


def test_missing_unrequired_evidence_is_unverified_not_blocking() -> None:
    results = evaluate_operational_blocks(
        _evidence(backup_failed=None),
        require_evidence=("kill_switch", "freeze"),
    )
    rules = {result.condition: result for result in results}
    assert rules["backup_failure"].blocked is False
    assert "unverified" in rules["backup_failure"].detail
    assert rules["kill_switch"].blocked is False  # evidence present and healthy


def test_results_persist_distinctly_per_condition(tmp_path: Path) -> None:
    store = OperationalBlockStore(db_path=tmp_path / "blocks.db")
    try:
        results = evaluate_operational_blocks(
            _evidence(freeze_open=True, broker_stale=True)
        )
        assert store.persist(ACCOUNT, results) == len(ALL_CONDITIONS)
        latest = store.latest(ACCOUNT)
        assert len(latest) == len(ALL_CONDITIONS)
        by_condition = {row["condition"]: row for row in latest}
        assert by_condition["freeze"]["blocked"] is True
        assert by_condition["stale_broker"]["blocked"] is True
        assert by_condition["kill_switch"]["blocked"] is False
        # Re-persisting a healthy evaluation keeps the newest verdict.
        store.persist(ACCOUNT, evaluate_operational_blocks(_evidence()))
        latest = store.latest(ACCOUNT)
        by_condition = {row["condition"]: row for row in latest}
        assert by_condition["freeze"]["blocked"] is False
    finally:
        store.close()


def test_block_results_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "blocks.db"
    store = OperationalBlockStore(db_path=path)
    try:
        store.persist(
            ACCOUNT, evaluate_operational_blocks(_evidence(kill_switch_active=True))
        )
    finally:
        store.close()
    reopened = OperationalBlockStore(db_path=path)
    try:
        latest = reopened.latest(ACCOUNT)
        by_condition = {row["condition"]: row for row in latest}
        assert by_condition["kill_switch"]["blocked"] is True
    finally:
        reopened.close()
