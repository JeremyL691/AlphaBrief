"""Every model citation is an exact reference to the current input catalog."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.schemas import CommitteeInput, MarketSnapshot
from committee_provider import canonical_fixture_payload


def _input() -> CommitteeInput:
    return CommitteeInput(
        snapshot=MarketSnapshot(
            symbol="EUR_USD",
            reference_price=Decimal("1.12"),
            captured_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        )
    )


class CitationProvider(FakeProviderAdapter):
    def __init__(self, *, phase: str, refs: Any, repair: bool = False) -> None:
        super().__init__(provider_name="fake", capabilities=["structured_output"])
        self.phase = phase
        self.refs = refs
        self.repair = repair
        self.requests: list[ModelRequest] = []

    def call(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        available = json.loads(request.metadata["available_evidence_ids"])
        phase = request.metadata.get("phase", "opening")
        role = request.metadata["committee_role"]
        output: dict[str, Any] = {
            "analysis": "Actual price snapshot supports this judgment.",
            "view": "bullish",
            "confidence": 0.8,
            "evidence_ids": [available[0]],
            "risks": [],
        }
        if phase == "opening":
            output.update(
                suggested_action="buy",
                target_position_pct="0.1",
                veto=False,
                needs_human_review=False,
            )
        else:
            output.update(stance="agreement", challenged_claim=None)
        output = canonical_fixture_payload(request, output)
        targeted = phase == self.phase and (role == "risk" or phase == "summary")
        if targeted and not (self.repair and request.call_kind == "repair"):
            if self.refs == "legacy":
                output["evidence"] = output.pop("evidence_ids")
            elif self.refs == "missing":
                del output["evidence_ids"]
            elif self.refs == "duplicate":
                output["evidence_ids"] = [available[0], available[0]]
            elif self.refs == "suffix":
                output["evidence_ids"] = [available[0] + ": explanation"]
            elif self.refs == "space":
                output["evidence_ids"] = [available[0] + " "]
            elif self.refs == "prefix":
                output["evidence_ids"] = [available[0].split(":", 1)[0]]
            else:
                output["evidence_ids"] = self.refs
        return ModelResponse(
            request_id=request.request_id,
            provider="fake",
            model="repaired-model"
            if request.call_kind == "repair"
            else "opening-model",
            output_text=json.dumps(output),
            structured_output=output,
            status="succeeded",
            finish_reason="stop",
        )


@pytest.mark.parametrize("phase", ["opening", "challenge", "summary"])
@pytest.mark.parametrize(
    "refs",
    [
        ["news:invented"],
        ["candle:invented"],
        ["broker:invented"],
        ["signal:invented"],
        ["ev-fake"],
        ["descriptive claim"],
        "legacy",
        "missing",
        "duplicate",
        "suffix",
        "space",
        "prefix",
        [""],
        [123],
    ],
)
def test_invalid_citations_never_enter_opinions_or_transcript(
    phase: str,
    refs: Any,
) -> None:
    provider = CitationProvider(phase=phase, refs=refs)
    result = TradingCommittee(gateway=ModelGateway([provider])).run(_input())
    assert result.transcript is not None
    assert any(phase in error or "risk:" in error for error in result.role_errors)
    assert not any(
        turn.phase == phase and (turn.role == "risk" or phase == "summary")
        for turn in result.transcript.turns
    )
    if phase == "opening":
        assert result.ok is False and result.plan is None
        assert not any(vote.role == "risk" for vote in result.votes)
    if phase == "summary":
        assert result.transcript.completed is False
    available = set(_input().evidence_ids)
    assert all(set(vote.cited_evidence_ids) <= available for vote in result.votes)


def test_repair_has_full_catalog_and_correct_successful_call_identity() -> None:
    payload = _input().model_copy(
        update={
            "time_horizon": "bounded factual context " * 300,
        }
    )
    provider = CitationProvider(phase="opening", refs=["news:invented"], repair=True)
    records: list[Any] = []
    result = TradingCommittee(
        gateway=ModelGateway([provider], record_sink=records.append),
        max_turns=5,
        challenge_rounds=0,
        repair_attempts=2,
    ).run(payload)
    assert result.ok is True and result.plan is not None
    repair_request = next(r for r in provider.requests if r.call_kind == "repair")
    for key, body in payload.evidence_catalog.items():
        assert f"{key}: {body}" in repair_request.input_text
    assert "evidence_ids" in repair_request.input_text
    vote = next(v for v in result.votes if v.role == "risk")
    assert vote.model_name == "repaired-model"
    repair_record = next(r for r in records if "repair" in r.request_id)
    assert vote.model_call_id == repair_record.call_id
    assert result.repair_attempts[0].model_call_id == vote.model_call_id
    assert result.transcript is not None
    turn = next(t for t in result.transcript.turns if t.role == "risk")
    assert turn.model_call_id == vote.model_call_id
    assert vote.evidence == vote.cited_evidence_ids == payload.evidence_ids


def test_invalid_reference_errors_do_not_echo_untrusted_secrets() -> None:
    secret = "sk-" + "adversarial-secret" * 4
    result = TradingCommittee(
        gateway=ModelGateway(
            [
                CitationProvider(phase="opening", refs=[secret]),
            ]
        )
    ).run(_input())
    assert result.plan is None
    assert secret not in "\n".join(result.role_errors)
    assert any("grounding_failed" in error for error in result.role_errors)
