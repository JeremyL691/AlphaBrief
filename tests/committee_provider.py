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


class GroundedProvider(FakeProviderAdapter):
    def call(self, request: ModelRequest) -> ModelResponse:
        response = super().call(request)
        return response.model_copy(
            update={
                "structured_output": grounded_payload(
                    request, response.structured_output
                ),
            }
        )
