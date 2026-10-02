"""The default cycle commits complete decision evidence before execution."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from _helpers import FakeExecutionBackend
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models import ModelGateway
from alphabrief_models.gateway import ModelCallRecord, ModelValidationRecord
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.daily_cycle import DailyTradingCycle
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.schemas import FinalCommitteeDecision, final_decision_id
from test_broker_input_quality import NOW
from test_manager_protocol import RawManager, snapshot

IDENTITY = "aic_actual_decision"
DECISION_ID = final_decision_id(IDENTITY, "EUR_USD")


@contextmanager
def runtime(
    path: Path,
    *,
    action: str = "open_long",
    units: Decimal = Decimal(0),
    repairs: int = 0,
    changes: dict[str, Any] | None = None,
) -> Iterator[
    tuple[
        DailyTradingCycle,
        AiTradingStore,
        ModelCallStore,
        FakeExecutionBackend,
        ModelGateway,
    ]
]:
    calls = ModelCallStore(path)
    store = AiTradingStore(path, require_model_audit=True)

    def record_call(record: ModelCallRecord) -> None:
        calls.save_call(record)

    def record_validation(record: ModelValidationRecord) -> None:
        calls.save_validation(record)

    gateway = ModelGateway(
        [RawManager(action, changes=changes)],
        record_sink=record_call,
        validation_sink=record_validation,
        clock=lambda: NOW,
    )
    engine = TradingCommittee(
        gateway=gateway,
        max_turns=5,
        challenge_rounds=0,
        repair_attempts=repairs,
        clock=lambda: NOW,
    )

    class ObservedBackend(FakeExecutionBackend):
        def submit(self, intent: Any, decision: Any, **kwargs: Any) -> Any:
            # Observe durability at the actual submission boundary, not later.
            saved = store.get_final_decision(intent.committee_decision_id)
            assert saved is not None and saved.model_audit_verified
            assert saved.decision_id == DECISION_ID and len(saved.votes) == 5
            assert set(saved.model_audit) == {
                "technical",
                "macro_news",
                "intermarket",
                "risk",
                "manager",
            }
            assert store.get_cycle_by_key("actual-round") is None
            for role, reference in saved.model_audit.items():
                assert reference.call_id == next(
                    vote.model_call_id for vote in saved.votes if vote.role == role
                )
                assert calls.get_call(reference.call_id) is not None
            return super().submit(intent, decision, **kwargs)

    backend = ObservedBackend()
    backend.positions["EUR_USD"] = units
    cycle = DailyTradingCycle(
        committee=engine,
        risk_gate=RiskGate(
            RiskLimitConfig(symbol_allowlist=frozenset({"EUR_USD"})),
            clock=lambda: NOW,
        ),
        execution_backend=backend,
        store=store,
        snapshot_loader=lambda _: snapshot(units),
        quantity_override=Decimal(2),
        enabled=True,
        trading_mode="on",
        clock=lambda: NOW,
        cycle_id_factory=lambda: IDENTITY,
    )
    try:
        yield cycle, store, calls, backend, gateway
    finally:
        store.close()
        calls.close()


@pytest.mark.parametrize(
    "action,units",
    [
        ("open_long", Decimal(0)),
        ("open_short", Decimal(0)),
        ("close", Decimal(10)),
        ("hold", Decimal(10)),
        ("no_trade", Decimal(0)),
    ],
)
def test_every_action_has_full_pre_execution_audit_and_reopens(
    tmp_path: Path,
    action: str,
    units: Decimal,
) -> None:
    path = tmp_path / "audit.duckdb"
    with runtime(path, action=action, units=units) as (
        cycle,
        store,
        _,
        backend,
        gateway,
    ):
        result = cycle.run(["EUR_USD"], cycle_key="actual-round")
        saved = store.get_final_decision(DECISION_ID)
        assert saved is not None and saved.plan.action == action
        assert (
            saved.input_quality.evidence_catalog
            == result.input_quality[0].evidence_catalog
        )
        assert saved.plan == result.plans[0] and saved.votes == result.votes
        assert len(gateway.call_records) == 5
        assert len(gateway.validation_records) == 5
        assert all(reference.input_hash for reference in saved.model_audit.values())
        if action in {"open_long", "open_short", "close"}:
            assert backend.submission_count == 1
            assert (
                result.attempts[0].order_intent_json["committee_decision_id"]
                == DECISION_ID
            )
        else:
            assert backend.submission_count == 0
    store = AiTradingStore(path, require_model_audit=True)
    try:
        reopened = store.get_final_decision(DECISION_ID)
        assert reopened == saved
        assert reopened is not None and reopened.created_at.tzinfo is not None
        assert isinstance(reopened.plan.target_position_pct, Decimal)
    finally:
        store.close()


def test_final_decision_write_failure_stops_before_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with runtime(tmp_path / "audit.duckdb") as (cycle, store, _, backend, gateway):

        def fail(_: FinalCommitteeDecision) -> FinalCommitteeDecision:
            raise OSError("audit write unavailable")

        monkeypatch.setattr(store, "save_final_decision", fail)
        with pytest.raises(OSError, match="audit write unavailable"):
            cycle.run(["EUR_USD"], cycle_key="actual-round")
        assert backend.submission_count == 0
        assert len(gateway.call_records) == 5
        assert store.get_final_decision(DECISION_ID) is None


def test_after_submit_cycle_write_failure_keeps_pre_execution_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "audit.duckdb"
    with runtime(path) as (cycle, store, _, backend, _):

        def fail(_: Any) -> str:
            raise OSError("post-submit cycle failure")

        monkeypatch.setattr(store, "save_cycle", fail)
        with pytest.raises(OSError, match="post-submit cycle failure"):
            cycle.run(["EUR_USD"], cycle_key="actual-round")
        assert backend.submission_count == 1
        assert store.get_cycle_by_key("actual-round") is None
    store = AiTradingStore(path)
    try:
        saved = store.get_final_decision(DECISION_ID)
        assert saved is not None and saved.model_audit_verified
    finally:
        store.close()


def test_repair_final_decision_uses_actual_successful_call(
    tmp_path: Path,
) -> None:
    with runtime(tmp_path / "audit.duckdb", repairs=1, changes={"confidence": 2}) as (
        cycle,
        store,
        _,
        backend,
        gateway,
    ):
        cycle.run(["EUR_USD"], cycle_key="actual-round")
        saved = store.get_final_decision(DECISION_ID)
        assert saved is not None
        assert saved.model_audit["manager"].call_id == gateway.call_records[-1].call_id
        assert saved.plan.manager_call_id == gateway.call_records[-1].call_id
        assert len(gateway.call_records) == 6 and backend.submission_count == 1
        assert gateway.validation_records[-2].verdict == "schema_rejected"


def test_same_identity_is_immutable_and_timestamp_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    with runtime(tmp_path / "audit.duckdb", action="no_trade") as (
        cycle,
        store,
        _,
        _,
        _,
    ):
        cycle.run(["EUR_USD"], cycle_key="actual-round")
        saved = store.get_final_decision(DECISION_ID)
        assert saved is not None
        assert (
            store.save_final_decision(
                saved.model_copy(
                    update={
                        "created_at": NOW + timedelta(seconds=1),
                    }
                )
            )
            == saved
        )
        changed = saved.model_copy(
            update={
                "plan": saved.plan.model_copy(
                    update={"rationale": "changed final decision"}
                ),
            }
        )
        with pytest.raises(ValueError, match="conflicting final decision"):
            store.save_final_decision(changed)
        assert store.get_final_decision(DECISION_ID) == saved


@pytest.mark.parametrize(
    "change",
    [
        "missing_call",
        "missing_validation",
        "wrong_cycle",
        "wrong_role",
        "wrong_input",
        "changed_vote",
        "missing_role",
        "bad_manager_id",
        "changed_input_body",
        "rejected_validation",
    ],
)
def test_missing_or_mismatched_model_evidence_stops_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    with runtime(tmp_path / "audit.duckdb") as (cycle, store, calls, backend, _):
        original = store.save_final_decision

        def corrupt(record: FinalCommitteeDecision) -> FinalCommitteeDecision:
            call_id = record.votes[0].model_call_id
            if change == "missing_call":
                calls._conn.execute(
                    "DELETE FROM model_call_records WHERE call_id = ?", [call_id]
                )
            elif change == "missing_validation":
                calls._conn.execute(
                    "DELETE FROM model_call_validations WHERE call_id = ?", [call_id]
                )
            elif change == "wrong_cycle":
                record = record.model_copy(update={"cycle_key": "different-round"})
            elif change == "wrong_role":
                payload = calls._conn.execute(
                    "SELECT audit_payload FROM model_call_records WHERE call_id = ?",
                    [call_id],
                ).fetchone()
                assert payload is not None
                data = json.loads(payload[0])
                data["request_metadata"]["committee_role"] = "manager"
                calls._conn.execute(
                    "UPDATE model_call_records SET audit_payload = ?::JSON "
                    "WHERE call_id = ?",
                    [json.dumps(data), call_id],
                )
            elif change == "wrong_input":
                record = record.model_copy(
                    update={
                        "input_quality": record.input_quality.model_copy(
                            update={"evidence_catalog": {}}
                        ),
                    }
                )
            elif change == "changed_vote":
                record = record.model_copy(
                    update={
                        "votes": [
                            record.votes[0].model_copy(update={"confidence": 0.9}),
                            *record.votes[1:],
                        ],
                    }
                )
            elif change == "missing_role":
                record = record.model_copy(update={"votes": record.votes[1:]})
            elif change == "changed_input_body":
                catalog = dict(record.input_quality.evidence_catalog)
                key = next(iter(catalog))
                catalog[key] = "changed input body under the old evidence ID"
                record = record.model_copy(
                    update={
                        "input_quality": record.input_quality.model_copy(
                            update={
                                "evidence_catalog": catalog,
                            }
                        ),
                    }
                )
            elif change == "rejected_validation":
                row = calls._conn.execute(
                    "SELECT validation_id, payload FROM model_call_validations "
                    "WHERE call_id = ?",
                    [call_id],
                ).fetchone()
                assert row is not None
                data = json.loads(row[1])
                data.update(
                    {"verdict": "grounding_rejected", "violation_hashes": ["e" * 64]}
                )
                calls._conn.execute(
                    "UPDATE model_call_validations SET payload = ?::JSON "
                    "WHERE validation_id = ?",
                    [json.dumps(data), row[0]],
                )
            else:
                record = record.model_copy(
                    update={
                        "plan": record.plan.model_copy(
                            update={"manager_call_id": "invented-call"}
                        ),
                    }
                )
            return original(record)

        monkeypatch.setattr(store, "save_final_decision", corrupt)
        with pytest.raises(ValueError, match="final decision"):
            cycle.run(["EUR_USD"], cycle_key="actual-round")
        assert backend.submission_count == 0
        assert store.get_final_decision(DECISION_ID) is None


def test_shadow_write_failure_keeps_decision_but_never_submits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with runtime(tmp_path / "audit.duckdb") as (cycle, store, _, backend, _):

        def fail(_: Any) -> None:
            raise OSError("shadow writer unavailable")

        monkeypatch.setattr(cycle, "_shadow_recorder", fail)
        with pytest.raises(OSError, match="shadow writer unavailable"):
            cycle.run(["EUR_USD"], cycle_key="actual-round")
        assert store.get_final_decision(DECISION_ID) is not None
        assert backend.submission_count == 0


def test_off_mode_still_persists_complete_decision_without_orders(
    tmp_path: Path,
) -> None:
    with runtime(tmp_path / "audit.duckdb") as (cycle, store, _, backend, _):
        cycle._trading_mode = "off"
        result = cycle.run(["EUR_USD"], cycle_key="actual-round")
        assert result.attempts[0].outcome == "blocked_trading_off"
        saved = store.get_final_decision(DECISION_ID)
        assert saved is not None and saved.model_audit_verified
        assert backend.submission_count == 0


def test_model_copy_secrets_are_scrubbed_without_changing_original(
    tmp_path: Path,
) -> None:
    with runtime(tmp_path / "audit.duckdb", action="no_trade") as (
        cycle,
        store,
        _,
        _,
        _,
    ):
        cycle.run(["EUR_USD"], cycle_key="actual-round")
        saved = store.get_final_decision(DECISION_ID)
        assert saved is not None
        copied = saved.model_copy(
            update={
                "cycle_id": "copy-audit",
                "decision_id": final_decision_id("copy-audit", "EUR_USD"),
                "plan": saved.plan.model_copy(
                    update={"rationale": "api_key=opaque-test-credential"}
                ),
            }
        )
        checked = store.save_final_decision(copied)
        assert "opaque-test-credential" not in checked.model_dump_json()
        assert "opaque-test-credential" in copied.plan.rationale
        assert store.get_final_decision(copied.decision_id) == checked


def test_existing_cycle_history_never_synthesizes_missing_final_audit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit.duckdb"
    with runtime(path, action="no_trade") as (cycle, store, _, _, _):
        cycle.run(["EUR_USD"], cycle_key="actual-round")
        store._conn.execute("DROP TABLE ai_final_decisions")
    store = AiTradingStore(path, require_model_audit=True)
    try:
        assert store.get_cycle_by_key("actual-round") is not None
        assert store.get_final_decision(DECISION_ID) is None
    finally:
        store.close()
