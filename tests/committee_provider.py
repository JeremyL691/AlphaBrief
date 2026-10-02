"""Explicit test responses grounded in the actual request's supplied facts."""

import json
from typing import Any

from alphabrief_models import FakeProviderAdapter, ModelRequest, ModelResponse


def grounded_payload(request: ModelRequest, payload: Any) -> Any:
    """Resolve only the deliberate fixture marker, never fabricated references."""
    if isinstance(payload, dict) and payload.get("evidence_ids") == ["input-evidence"]:
        available = json.loads(request.metadata["available_evidence_ids"])
        assert available
        return {**payload, "evidence_ids": [available[0]]}
    return payload


def canonical_fixture_payload(request: ModelRequest, payload: Any) -> Any:
    """Emit equivalent analyst fixtures; production never accepts the old format.

    Only complete, recognized old fixtures are migrated. Missing/extra fields and
    fabricated citations remain invalid; strict-schema tests use raw responses.
    """
    if (
        request.metadata.get("phase", "opening") != "opening"
        or request.metadata.get("committee_role")
        not in {"technical", "macro_news", "intermarket", "risk"}
    ):
        return payload
    required = {
        "analysis",
        "view",
        "confidence",
        "evidence_ids",
        "suggested_action",
        "target_position_pct",
    }
    allowed = required | {"risks", "veto", "needs_human_review"}
    if (
        not isinstance(payload, dict)
        or not required <= payload.keys()
        or not payload.keys() <= allowed
        or not isinstance(payload["view"], str)
    ):
        return payload
    stance = {
        "bullish": "long",
        "bearish": "short",
        "neutral": "flat",
        "uncertain": "flat",
    }.get(payload["view"])
    risks = payload.get("risks", [])
    if (
        stance is None
        or not isinstance(risks, list)
        or not all(isinstance(risk, str) for risk in risks)
    ):
        return payload
    return {
        "stance": stance,
        "confidence": payload["confidence"],
        "horizon_hours": 24,
        "key_points": [payload["analysis"], *risks],
        "evidence_ids": payload["evidence_ids"],
        "veto": payload.get("veto", False),
    }


class GroundedProvider(FakeProviderAdapter):
    def call(self, request: ModelRequest) -> ModelResponse:
        response = super().call(request)
        return response.model_copy(
            update={
                "structured_output": canonical_fixture_payload(
                    request, grounded_payload(request, response.structured_output)
                ),
            }
        )
