"""Schema and grounding judgments are durable facts tied to actual responses."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import duckdb
import pytest
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models import ModelGateway, ModelRequest, ModelResponse
from alphabrief_models.gateway import ModelCallRecord, ModelValidationRecord
from alphabrief_trader import (
    CommitteeInput,
    MarketSnapshot,
    TradingCommittee,
    model_factory,
)
from committee_provider import GroundedProvider, canonical_fixture_payload

NOW = datetime(2026, 10, 2, tzinfo=UTC)


class PhaseProvider(GroundedProvider):
    def __init__(self, phase: str, kind: str) -> None:
        super().__init__(capabilities=["structured_output"])
        self.phase = phase
        self.kind = kind

    def call(self, request: ModelRequest) -> ModelResponse:
        phase = request.metadata["phase"]
        output = {
            "analysis": "Evidence supports no entry.",
            "view": "neutral",
            "confidence": 0.8,
            "evidence_ids": [json.loads(request.metadata["available_evidence_ids"])[0]],
        }
        if phase == "opening":
            output.update(
                {"risks": [], "suggested_action": "hold", "target_position_pct": "0"}
            )
        else:
            output["stance"] = "agreement"
        output = canonical_fixture_payload(request, output)
        role = "manager" if phase == "summary" else "technical"
        targeted = phase == self.phase and request.metadata["committee_role"] == role
        if targeted and request.call_kind != "repair":
            if self.kind == "invalid_json":
                return ModelResponse(
                    request_id=request.request_id,
                    provider=self.provider_name,
                    model=self.model_name,
                    output_text="bad JSON from actual provider",
                    finish_reason="stop",
                )
            if self.kind == "invalid_schema":
                output["confidence"] = 2
            elif self.kind == "invalid_grounding":
                output["evidence_ids"] = ["invented:actual-rejected-reference"]
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=json.dumps(output),
            structured_output=output,
            finish_reason="stop",
        )


def _payload() -> CommitteeInput:
    return CommitteeInput(
        snapshot=MarketSnapshot(
            symbol="EUR_USD", reference_price=Decimal("1.12"), captured_at=NOW
        ),
        cycle_key="audited-round",
    )


def _recorder(store: ModelCallStore) -> Callable[[ModelCallRecord], None]:
    def save(record: ModelCallRecord) -> None:
        store.save_call(record)

    return save


@pytest.mark.parametrize("phase", ["opening", "challenge", "summary"])
@pytest.mark.parametrize(
    "kind", ["accepted", "invalid_json", "invalid_schema", "invalid_grounding"]
)
def test_every_discussion_phase_persists_exact_parse_and_grounding_verdict(
    tmp_path: Path,
    phase: str,
    kind: str,
) -> None:
    path = tmp_path / "validation.duckdb"
    store = ModelCallStore(path)
    gateway = ModelGateway(
        [PhaseProvider(phase, kind)],
        record_sink=_recorder(store),
        validation_sink=store.save_validation,
    )
    result = TradingCommittee(gateway=gateway, max_turns=10, challenge_rounds=1).run(
        _payload()
    )
    assert len(gateway.validation_records) == len(gateway.call_records)
    targeted = [
        record
        for record in gateway.call_records
        if record.audit_payload is not None
        and record.audit_payload["request_metadata"]["phase"] == phase
        and record.audit_payload["request_metadata"]["committee_role"]
        == ("manager" if phase == "summary" else "technical")
    ]
    assert len(targeted) == 1
    call = targeted[0]
    original = store.get_call(call.call_id)
    store.close()
    reader = ModelCallStore(path, read_only=True)
    try:
        events = reader.list_validations(call.call_id)
        assert len(events) == 1
        event = events[0]
        assert reader.get_call(call.call_id) == original
        assert event["call_id"] == call.call_id
        assert (
            event["validation_id"]
            == sha256((call.call_id + ":" + event["schema_hash"]).encode()).hexdigest()
        )
        assert event["target_schema"]["type"] == "object"
        if kind == "accepted":
            assert event["verdict"] == "accepted"
            assert event["parsed_output"]["confidence"] == 0.8
            assert not event["violation_hashes"] and event["error_code"] is None
        elif kind == "invalid_grounding":
            assert event["verdict"] == "grounding_rejected"
            assert event["parsed_output"] is not None
            assert len(event["violation_hashes"]) == 1
            assert len(event["violation_hashes"][0]) == 64
        else:
            assert event["verdict"] == "schema_rejected"
            assert event["parsed_output"] is None
            assert event["error_code"] == (
                "invalid_json" if kind == "invalid_json" else "schema_validation_failed"
            )
        if phase == "opening" and kind != "accepted":
            assert result.plan is None
    finally:
        reader.close()


@pytest.mark.parametrize(
    "kind", ["invalid_json", "invalid_schema", "invalid_grounding"]
)
def test_production_factory_records_original_rejection_and_actual_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "fake")
    monkeypatch.setattr(
        model_factory,
        "build_conservative_fake_provider",
        lambda: PhaseProvider("opening", kind),
    )
    store = ModelCallStore(tmp_path / "production.duckdb")
    try:
        committee = model_factory.build_ai_trading_committee(
            record_sink=_recorder(store),
            validation_sink=store.save_validation,
        )
        result = committee.run(_payload())
        assert result.ok
        calls = store.list_calls_by_cycle("audited-round")
        assert len(calls) == 6
        events = {
            row["call_id"]: store.list_validations(row["call_id"])[0] for row in calls
        }
        assert sum(e["verdict"] == "accepted" for e in events.values()) == 5
        rejection = (
            "grounding_rejected" if kind == "invalid_grounding" else "schema_rejected"
        )
        assert sum(e["verdict"] == rejection for e in events.values()) == 1
        technical = next(v for v in result.votes if v.role == "technical")
        assert technical.model_call_id is not None
        repaired = store.get_call(technical.model_call_id)
        assert (
            repaired is not None and repaired["audit_payload"]["call_kind"] == "repair"
        )
        assert events[technical.model_call_id]["verdict"] == "accepted"
    finally:
        store.close()


def test_validation_is_immutable_idempotent_and_requires_a_recorded_response(
    tmp_path: Path,
) -> None:
    store = ModelCallStore(tmp_path / "immutable.duckdb")
    gateway = ModelGateway(
        [PhaseProvider("opening", "accepted")],
        record_sink=_recorder(store),
        validation_sink=store.save_validation,
    )
    try:
        TradingCommittee(gateway=gateway, max_turns=5, challenge_rounds=0).run(
            _payload()
        )
        record = gateway.validation_records[0]
        store.save_validation(record)
        assert len(store.list_validations(record.call_id)) == 1
        assert record.parsed_output is not None
        conflicting = record.model_copy(
            update={"parsed_output": {**record.parsed_output, "confidence": 0.1}}
        )
        with pytest.raises(ValueError, match="conflicting"):
            store.save_validation(conflicting)
        unknown = "unrecorded-call"
        forged = record.model_copy(
            update={
                "call_id": unknown,
                "validation_id": sha256(
                    (unknown + ":" + record.schema_hash).encode()
                ).hexdigest(),
            }
        )
        with pytest.raises(ValueError, match="persisted"):
            store.save_validation(forged)
        connection = duckdb.connect(str(tmp_path / "immutable.duckdb"))
        connection.execute("DROP TABLE model_call_validations")
        connection.close()
        assert store.list_validations(record.call_id) == []
    finally:
        store.close()


def test_validation_write_failure_stops_before_plan() -> None:
    def fail(record: ModelValidationRecord) -> None:
        raise RuntimeError("audit storage unavailable")

    gateway = ModelGateway([PhaseProvider("opening", "accepted")], validation_sink=fail)
    with pytest.raises(RuntimeError, match="audit storage"):
        TradingCommittee(gateway=gateway, max_turns=5, challenge_rounds=0).run(
            _payload()
        )
    assert len(gateway.call_records) == 1
    assert gateway.validation_records == []


def test_exhausted_repairs_keep_all_rejections_and_produce_no_plan(
    tmp_path: Path,
) -> None:
    class AlwaysInvalid(PhaseProvider):
        def call(self, request: ModelRequest) -> ModelResponse:
            if request.call_kind == "repair":
                return ModelResponse(
                    request_id=request.request_id,
                    provider=self.provider_name,
                    model=self.model_name,
                    output_text="another invalid repair",
                    finish_reason="stop",
                )
            return super().call(request)

    store = ModelCallStore(tmp_path / "exhausted.duckdb")
    try:
        gateway = ModelGateway(
            [AlwaysInvalid("opening", "invalid_json")],
            record_sink=_recorder(store),
            validation_sink=store.save_validation,
        )
        result = TradingCommittee(
            gateway=gateway, max_turns=5, challenge_rounds=0, repair_attempts=2
        ).run(_payload())
        assert result.plan is None
        calls = store.list_calls_by_cycle("audited-round")
        assert len(calls) == 7
        assert sum(row["audit_payload"]["call_kind"] == "repair" for row in calls) == 2
        events = [store.list_validations(row["call_id"])[0] for row in calls]
        assert sum(e["verdict"] == "schema_rejected" for e in events) == 3
        assert sum(e["verdict"] == "accepted" for e in events) == 4
    finally:
        store.close()
