"""Actual provider responses survive parsing, repair, restart and safe migration."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb
import pytest
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_models.gateway import ModelCallRecord
from alphabrief_models.repair import repair_structured_output
from alphabrief_models.structured_output import parse_structured_output
from pydantic import BaseModel

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def _recorder(store: ModelCallStore) -> Callable[[ModelCallRecord], None]:
    def save(record: ModelCallRecord) -> None:
        store.save_call(record)

    return save


def _request() -> ModelRequest:
    return ModelRequest(
        request_id="audit-opening",
        task_type="symbol_research",
        prompt_version="actual-prompt-version",
        input_text="Actual frozen facts",
        required_capabilities=["text_generation"],
        cycle_key="audit-round",
        metadata={"committee_role": "risk", "phase": "opening", "symbol": "EUR_USD"},
    )


class Answer(BaseModel):
    answer: str


def test_full_raw_and_structured_responses_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "audit.duckdb"
    raw = "first line\n" + "完整响应 " * 4000 + "\nlast line"
    payload = {
        "answer": "provider structured value",
        "nested": [1, None, {"flag": True}],
    }
    store = ModelCallStore(path)
    gateway = ModelGateway(
        [FakeProviderAdapter(output_text=raw, structured_output=payload)],
        record_sink=_recorder(store),
        clock=lambda: NOW,
    )
    result = gateway.invoke(_request())
    assert result.response is not None and result.response.output_text == raw
    assert result.record.output_hash == sha256(raw.encode()).hexdigest()
    assert (
        result.record.input_hash == sha256(_request().input_text.encode()).hexdigest()
    )
    store.close()
    with_store = ModelCallStore(path, read_only=True)
    try:
        row = with_store.get_call(result.record.call_id)
        assert row is not None
        assert row["prompt_version"] == "actual-prompt-version"
        assert row["audit_payload"] == {
            "output_text": raw,
            "structured_output": payload,
            "request_metadata": _request().metadata,
            "call_kind": "normal",
            "response_status": "succeeded",
            "finish_reason": "stop",
        }
        assert (
            with_store.list_calls_by_cycle("audit-round")[0]["audit_payload"]
            == row["audit_payload"]
        )
    finally:
        with_store.close()


def test_failed_parse_and_successful_repair_keep_distinct_actual_outputs(
    tmp_path: Path,
) -> None:
    malformed = "not JSON\n" + "original bad response " * 1000
    repaired = json.dumps({"answer": "actual successful repair"})

    class SequenceProvider(FakeProviderAdapter):
        calls = 0

        def call(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model=self.model_name,
                output_text=malformed if self.calls == 1 else repaired,
                finish_reason="stop",
            )

    store = ModelCallStore(tmp_path / "repair.duckdb")
    try:
        gateway = ModelGateway([SequenceProvider()], record_sink=_recorder(store))
        initial = gateway.invoke(_request())
        assert initial.response is not None
        assert not parse_structured_output(initial.response, target=Answer).ok
        result = repair_structured_output(
            gateway=gateway,
            request=_request(),
            target=Answer,
            raw_output=malformed,
            failure_reason="invalid_json",
            max_attempts=1,
        )
        assert result.ok and result.response is not None
        repair_id = result.attempts[0].model_call_id
        assert repair_id is not None and repair_id != initial.record.call_id
        original_row = store.get_call(initial.record.call_id)
        repair_row = store.get_call(repair_id)
        assert original_row is not None and repair_row is not None
        assert original_row["audit_payload"]["output_text"] == malformed
        assert repair_row["audit_payload"]["output_text"] == repaired
        assert repair_row["audit_payload"]["call_kind"] == "repair"
        assert repair_row["request_id"] == "audit-opening_repair_1"
        assert repair_row["input_hash"] != original_row["input_hash"]
        assert len(store.list_calls_by_cycle("audit-round")) == 2
    finally:
        store.close()


def test_raw_payload_and_model_copy_cannot_persist_credentials(tmp_path: Path) -> None:
    key = "sk-" + "synthetic-sensitive-value" * 2
    account = "-".join(["101", "004", "7654321", "001"])
    broker_token = "a" * 32 + "-" + "b" * 32
    jwt = "eyJ" + "abcdef" + ".payload.signature"
    raw = f"Bearer abc\n{key}\n{account}\n{broker_token}\n{jwt}\npassword=short\nend"
    payload: dict[str, Any] = {
        "nested": [{"access_token": "short", "answer": key}],
        "account_id": account,
    }
    provider = FakeProviderAdapter(output_text=raw, structured_output=payload)
    gateway = ModelGateway([provider])
    result = gateway.invoke(_request())
    assert result.response is not None and result.response.output_text == raw
    assert result.record.audit_payload is not None
    dumped = json.dumps(result.record.audit_payload)
    for secret in (key, account, broker_token, jwt, "Bearer abc", "short"):
        assert secret not in dumped
    assert result.record.output_hash == sha256(raw.encode()).hexdigest()
    store = ModelCallStore(tmp_path / "safe.duckdb")
    try:
        forged = result.record.model_copy(
            update={
                "audit_payload": {
                    "output_text": raw,
                    "structured_output": payload,
                }
            }
        )
        store.save_call(forged)
        row = store.get_call(forged.call_id)
        assert row is not None
        dumped = json.dumps(row["audit_payload"])
        for secret in (key, account, broker_token, jwt, "Bearer abc", "short"):
            assert secret not in dumped
        # Scrubbing does not mutate the provider response or the caller's payload.
        assert payload["nested"][0]["access_token"] == "short"
        assert (
            forged.audit_payload is not None
            and forged.audit_payload["output_text"] == raw
        )
    finally:
        store.close()


def test_old_read_only_and_writable_migration_preserve_unknown_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "old.duckdb"
    record = ModelGateway([FakeProviderAdapter()]).invoke(_request()).record
    store = ModelCallStore(path)
    store.save_call(record.model_copy(update={"audit_payload": None}))
    store.close()
    legacy = duckdb.connect(str(path))
    legacy.execute("ALTER TABLE model_call_records DROP COLUMN audit_payload")
    legacy.close()
    reader = ModelCallStore(path, read_only=True)
    try:
        row = reader.get_call(record.call_id)
        assert row is not None and row["audit_payload"] is None
        assert (
            reader.list_calls_by_cycle("audit-round")[0]["output_hash"]
            == record.output_hash
        )
    finally:
        reader.close()
    writer = ModelCallStore(path)
    try:
        row = writer.get_call(record.call_id)
        assert row is not None and row["audit_payload"] is None
        writer.save_call(record)
        assert writer.get_call(record.call_id) == row  # Never backfill an old response.
        newer = record.model_copy(update={"call_id": "new-actual-call"})
        writer.save_call(newer)
        stored = writer.get_call(newer.call_id)
        assert stored is not None and stored["audit_payload"] == newer.audit_payload
    finally:
        writer.close()


@pytest.mark.parametrize("kind", ["rejected", "failed"])
def test_no_response_is_null_instead_of_fabricated_empty_text(
    kind: str, tmp_path: Path
) -> None:
    class FailingProvider(FakeProviderAdapter):
        def call(self, request: ModelRequest) -> ModelResponse:
            raise TimeoutError("provider unavailable")

    store = ModelCallStore(tmp_path / "missing.duckdb")
    try:
        gateway = ModelGateway(
            [FailingProvider()] if kind == "failed" else [],
            record_sink=_recorder(store),
        )
        result = gateway.invoke(_request())
        assert result.response is None and result.record.status == kind
        row = store.get_call(result.record.call_id)
        assert row is not None
        assert row["audit_payload"]["output_text"] is None
        assert row["audit_payload"]["structured_output"] is None
        assert row["audit_payload"]["request_metadata"]["committee_role"] == "risk"
        assert row["output_hash"] == ""
    finally:
        store.close()


def test_explicit_fallback_preserves_each_attempt_without_inventing_a_response(
    tmp_path: Path,
) -> None:
    class FailingPrimary(FakeProviderAdapter):
        def call(self, request: ModelRequest) -> ModelResponse:
            raise TimeoutError("primary timeout")

    store = ModelCallStore(tmp_path / "fallback.duckdb")
    try:
        gateway = ModelGateway(
            [
                FailingPrimary(provider_name="primary"),
                FakeProviderAdapter(
                    provider_name="explicit-fallback", output_text="actual fallback"
                ),
            ],
            fallback_enabled=True,
            fallback_eligible=lambda record: True,
            record_sink=_recorder(store),
        )
        result = gateway.invoke(_request())
        rows = {
            row["provider"]: row for row in store.list_calls_by_cycle("audit-round")
        }
        assert len(rows) == 2
        assert rows["primary"]["audit_payload"]["output_text"] is None
        assert rows["primary"]["status"] == "failed"
        assert (
            rows["explicit-fallback"]["audit_payload"]["output_text"]
            == "actual fallback"
        )
        assert rows["explicit-fallback"]["call_id"] == result.record.call_id
        assert rows["primary"]["call_id"] != result.record.call_id
    finally:
        store.close()


def test_received_empty_text_and_decimal_payload_are_preserved(tmp_path: Path) -> None:
    from decimal import Decimal

    store = ModelCallStore(tmp_path / "empty.duckdb")
    try:
        gateway = ModelGateway(
            [
                FakeProviderAdapter(
                    output_text="", structured_output={"amount": Decimal("1.2300")}
                )
            ],
            record_sink=_recorder(store),
        )
        result = gateway.invoke(_request())
        assert result.response is not None
        row = store.get_call(result.record.call_id)
        assert row is not None
        assert row["audit_payload"]["output_text"] == ""
        assert row["audit_payload"]["structured_output"] == {"amount": "1.2300"}
    finally:
        store.close()
