"""M13-W05: locked deterministic OpenAPI contract.

Covers AC-M13-W05-01/02: the generated OpenAPI is deterministic and
declares every read and approved mutation schema, error model, cursor,
freshness field, idempotency header, and correlation identifier;
contract tests prove cursor stability, bounded page sizes, UTC
serialization, decimal fidelity, unknown-field rejection, and no
sensitive example values.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_api.main import create_app
from alphabrief_api.openapi_contract import (
    CONTRACT_EXTENSION,
    CORRELATION_HEADER,
    IDEMPOTENCY_HEADER,
    OPENAPI_CONTRACT_VERSION,
    build_deterministic_openapi,
    scan_for_sensitive_values,
    verify_openapi_contract,
)
from alphabrief_core import (
    READ_DOMAINS,
    FreshnessVerdict,
    PageCursor,
    Provenance,
    VersionedReadEnvelope,
    build_read_envelope,
)
from alphabrief_core.write_contracts import OPERATOR_MUTATIONS
from pydantic import ValidationError


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return build_deterministic_openapi(create_app())


class TestDeterministicOpenapi:
    def test_generation_is_byte_deterministic(self) -> None:
        first = build_deterministic_openapi(create_app())
        second = build_deterministic_openapi(create_app())
        assert json.dumps(first, sort_keys=True) == json.dumps(
            second, sort_keys=True
        )

    def test_contract_extension_is_declared(self, schema: dict[str, Any]) -> None:
        extension = schema["x-alphabrief-contract"]
        assert isinstance(extension, dict)
        assert extension["contract_version"] == OPENAPI_CONTRACT_VERSION
        assert set(extension["read_domains"]) == READ_DOMAINS
        assert set(extension["operator_mutations"]) == OPERATOR_MUTATIONS
        assert extension["idempotency_header"] == IDEMPOTENCY_HEADER
        assert extension["correlation_header"] == CORRELATION_HEADER

    def test_error_model_cursor_freshness_are_declared(
        self, schema: dict[str, Any]
    ) -> None:
        extension = schema["x-alphabrief-contract"]
        assert set(extension["error_model"]) == {
            "error_code",
            "message",
            "resource",
        }
        assert set(extension["cursor_fields"]) == {
            "cursor",
            "next_cursor",
            "has_more",
            "limit",
            "count",
        }
        assert set(extension["freshness_fields"]) == {
            "status",
            "age_seconds",
            "max_age_seconds",
        }

    def test_verification_passes(self, schema: dict[str, Any]) -> None:
        verdict = verify_openapi_contract(schema)
        assert verdict.passed, verdict.issues

    def test_verification_fails_closed_on_missing_extension(self) -> None:
        verdict = verify_openapi_contract({"paths": {}})
        assert not verdict.passed
        assert any("extension" in issue for issue in verdict.issues)

    def test_no_sensitive_example_values(self, schema: dict[str, Any]) -> None:
        assert scan_for_sensitive_values(schema) == []


class TestCursorAndFreshness:
    def test_cursor_round_trip_is_stable(self) -> None:
        cursor = PageCursor(
            cursor="c1", next_cursor="c2", has_more=True, limit=50, count=3
        )
        payload = json.loads(cursor.model_dump_json())
        restored = PageCursor.model_validate(payload)
        assert restored == cursor
        assert json.loads(cursor.model_dump_json()) == json.loads(
            cursor.model_dump_json()
        )

    def test_cursor_contract_matches_declaration(self) -> None:
        assert set(PageCursor.model_fields) == set(
            CONTRACT_EXTENSION["cursor_fields"]
        )

    def test_freshness_verdict_matches_declaration(self) -> None:
        assert set(FreshnessVerdict.model_fields) == set(
            CONTRACT_EXTENSION["freshness_fields"]
        )

    def test_bounded_page_sizes(self) -> None:
        # Operational equity caps limit at [1, 1000].
        client = __import__(
            "fastapi.testclient", fromlist=["TestClient"]
        ).TestClient(create_app())
        assert client.get("/api/v1/operational/equity?limit=0").status_code == 422
        assert client.get("/api/v1/operational/equity?limit=5000").status_code == 422


class TestSerializationFidelity:
    def test_utc_serialization(self) -> None:
        envelope = build_read_envelope(
            domain="scheduler",
            resource="status",
            items=(),
            provenance=Provenance(
                source="s",
                data_version="v",
                retrieved_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
            ),
            freshness=FreshnessVerdict(status="unknown"),
            pagination=PageCursor(limit=50, count=0),
            generated_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        )
        payload = envelope.model_dump(mode="json")
        assert datetime.fromisoformat(payload["generated_at"]) == datetime(
            2026, 8, 14, 0, 0, tzinfo=UTC
        )
        assert datetime.fromisoformat(
            payload["provenance"]["retrieved_at"]
        ).utcoffset() == timedelta(0)

    def test_decimal_fidelity(self) -> None:
        value = Decimal("123.45678901234567890123")
        payload = VersionedReadEnvelope(
            schema_version="read-v1",
            domain="risk",
            resource="r",
            generated_at=datetime(2026, 8, 14, tzinfo=UTC),
            state="complete",
            provenance=Provenance(
                source="s",
                data_version="v",
                retrieved_at=datetime(2026, 8, 14, tzinfo=UTC),
            ),
            freshness=FreshnessVerdict(status="unknown"),
            pagination=PageCursor(limit=1, count=1),
            items=({"id": "x", "amount": str(value)},),
        ).model_dump(mode="json")
        assert Decimal(payload["items"][0]["amount"]) == value

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VersionedReadEnvelope.model_validate(
                {
                    "schema_version": "read-v1",
                    "domain": "risk",
                    "resource": "r",
                    "generated_at": "2026-08-14T00:00:00+00:00",
                    "state": "complete",
                    "provenance": {
                        "source": "s",
                        "data_version": "v",
                        "retrieved_at": "2026-08-14T00:00:00+00:00",
                    },
                    "freshness": {"status": "unknown"},
                    "pagination": {"limit": 1, "count": 1},
                    "items": (),
                    "unexpected": True,
                }
            )
