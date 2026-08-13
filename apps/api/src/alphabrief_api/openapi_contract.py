"""Deterministic OpenAPI contract for all exposed resources (M13-W05).

Builds the application OpenAPI deterministically and attaches a
versioned ``x-alphabrief-contract`` extension declaring the shared
semantics every consumer can rely on: the 14 read domains, the 7
approved operator mutations, the typed error model, cursor and
freshness fields, the idempotency header, and the correlation
identifier. ``verify_openapi_contract`` fails closed on any missing
declaration (REQ-PLAT-009, REQ-UI-001, REQ-UI-002, REQ-UI-006).
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

from alphabrief_core.read_contracts import READ_DOMAINS
from alphabrief_core.write_contracts import (
    APPROVED_ENDPOINTS,
    OPERATOR_MUTATIONS,
)
from pydantic import BaseModel, ConfigDict

OPENAPI_CONTRACT_VERSION = "openapi-contract-1"

#: Headers every mutation and read must carry / may carry.
IDEMPOTENCY_HEADER = "Idempotency-Key"
CORRELATION_HEADER = "X-Correlation-ID"

#: Shared semantics declared once in the contract extension.
CONTRACT_EXTENSION: dict[str, Any] = {
    "contract_version": OPENAPI_CONTRACT_VERSION,
    "read_domains": sorted(READ_DOMAINS),
    "operator_mutations": sorted(OPERATOR_MUTATIONS),
    "approved_endpoints": {
        mutation: sorted(endpoints)
        for mutation, endpoints in sorted(APPROVED_ENDPOINTS.items())
    },
    "error_model": {
        "error_code": "string",
        "message": "string",
        "resource": "string | null",
    },
    "cursor_fields": {
        "cursor": "string | null",
        "next_cursor": "string | null",
        "has_more": "boolean",
        "limit": "integer",
        "count": "integer",
    },
    "freshness_fields": {
        "status": "fresh | stale | unknown",
        "age_seconds": "integer | null",
        "max_age_seconds": "integer | null",
    },
    "idempotency_header": IDEMPOTENCY_HEADER,
    "correlation_header": CORRELATION_HEADER,
}


class OpenapiContractVerdict(BaseModel):
    """One deterministic verification verdict over the OpenAPI schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    issues: tuple[str, ...]


def build_deterministic_openapi(app: Any) -> dict[str, Any]:
    """The deterministic OpenAPI schema with the contract extension.

    The base schema is byte-stable (sorted keys); the extension is
    attached so every consumer sees the same shared semantics.
    """
    schema = app.openapi()
    extension = json.loads(json.dumps(CONTRACT_EXTENSION, sort_keys=True))
    schema["x-alphabrief-contract"] = extension
    return cast(
        dict[str, Any],
        json.loads(json.dumps(schema, sort_keys=True, separators=(",", ":"))),
    )


def verify_openapi_contract(schema: dict[str, Any]) -> OpenapiContractVerdict:
    """Verify every required declaration exists in the schema."""
    issues: list[str] = []
    extension = schema.get("x-alphabrief-contract")
    if extension is None:
        issues.append("missing x-alphabrief-contract extension")
    else:
        for key in (
            "contract_version",
            "read_domains",
            "operator_mutations",
            "approved_endpoints",
            "error_model",
            "cursor_fields",
            "freshness_fields",
            "idempotency_header",
            "correlation_header",
        ):
            if key not in extension:
                issues.append(f"contract extension missing {key!r}")
        if extension.get("contract_version") != OPENAPI_CONTRACT_VERSION:
            issues.append("contract version mismatch")
        if set(extension.get("read_domains", [])) != READ_DOMAINS:
            issues.append("read_domains do not match the required 14")
        if set(extension.get("operator_mutations", [])) != OPERATOR_MUTATIONS:
            issues.append("operator_mutations do not match the approved 7")
        if extension.get("idempotency_header") != IDEMPOTENCY_HEADER:
            issues.append("idempotency header mismatch")
        if extension.get("correlation_header") != CORRELATION_HEADER:
            issues.append("correlation header mismatch")

    paths = schema.get("paths", {})
    for required in (
        "/api/v1/operational/portfolio",
        "/api/v1/operational/equity",
        "/api/v1/trace/cycles/{cycle_id}",
        "/api/v1/broker/status",
        "/api/v1/scheduler/status",
        "/api/v1/ai/history",
        "/api/v1/data/catalog",
    ):
        if required not in paths:
            issues.append(f"missing required resource path {required!r}")

    return OpenapiContractVerdict(
        passed=not issues,
        issues=tuple(issues),
    )


#: Tokens that must never appear in schema descriptions or examples.
_SENSITIVE_PATTERNS = (
    re.compile(r"bearer", re.IGNORECASE),
    re.compile(r"api[-_]?key", re.IGNORECASE),
    re.compile(r"authorization"),
)


def scan_for_sensitive_values(schema: dict[str, Any]) -> list[str]:
    """Return every sensitive token found in the schema text."""
    text = json.dumps(schema)
    return [
        pattern.pattern
        for pattern in _SENSITIVE_PATTERNS
        if pattern.search(text) is not None
    ]


__all__ = [
    "CONTRACT_EXTENSION",
    "CORRELATION_HEADER",
    "IDEMPOTENCY_HEADER",
    "OPENAPI_CONTRACT_VERSION",
    "OpenapiContractVerdict",
    "build_deterministic_openapi",
    "scan_for_sensitive_values",
    "verify_openapi_contract",
]
