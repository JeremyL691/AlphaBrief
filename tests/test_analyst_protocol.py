"""GUIDE 5.4 analyst output is strict at the actual model boundary."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_trader import CommitteeInput, MarketSnapshot, TradingCommittee
from alphabrief_trader.committee import CommitteeResult
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.schemas import DailyCycleRecord

NOW = datetime(2026, 10, 2, tzinfo=UTC)


class RawProtocolProvider(FakeProviderAdapter):
    """Return raw JSON only; no fixture conversion or production compatibility."""

    def __init__(
        self,
        *,
        overrides: dict[str, Any] | None = None,
        missing: str | None = None,
        legacy: bool = False,
    ) -> None:
        super().__init__(capabilities=["structured_output"])
        self.overrides = overrides or {}
        self.missing = missing
        self.legacy = legacy
        self.requests: list[ModelRequest] = []

    def call(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        evidence = [json.loads(request.metadata["available_evidence_ids"])[0]]
        legacy: dict[str, Any] = {
            "analysis": "Observed reference price is 1.12.",
            "view": "bullish",
            "confidence": 0.8,
            "evidence_ids": evidence,
            "risks": [],
            "suggested_action": "buy",
            "target_position_pct": "0.1",
            "veto": False,
            "needs_human_review": False,
        }
        output: dict[str, Any] = {
            "stance": "long",
            "confidence": 0.8,
            "horizon_hours": 24,
            "key_points": [
                "Observed reference price is 1.12.",
                "Inputs do not establish causal claims.",
            ],
            "evidence_ids": evidence,
            "veto": False,
        }
        role = request.metadata["committee_role"]
        if role == "manager":
            output = {
                "action": "open_long",
                "confidence": 0.8,
                "stop_atr_multiple": 1.5,
                "take_profit_r_multiple": 2.0,
                "rationale": "Observed reference price is 1.12.",
                "evidence_ids": evidence,
            }
        elif role == "technical" and request.call_kind != "repair":
            if self.legacy:
                output = legacy
            else:
                output.update(self.overrides)
                if self.missing is not None:
                    output.pop(self.missing)
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=json.dumps(output),
            finish_reason="stop",
        )


def _run(
    provider: RawProtocolProvider, *, repairs: int = 0
) -> tuple[CommitteeResult, ModelGateway]:
    payload = CommitteeInput(
        snapshot=MarketSnapshot(
            symbol="EUR_USD", reference_price=Decimal("1.12"), captured_at=NOW
        ),
        cycle_key="analyst-protocol-round",
    )
    gateway = ModelGateway([provider])
    result = TradingCommittee(
        gateway=gateway, max_turns=5, challenge_rounds=0, repair_attempts=repairs
    ).run(payload)
    return result, gateway


@pytest.mark.parametrize(
    "stance,view", [("long", "bullish"), ("short", "bearish"), ("flat", "neutral")]
)
def test_native_fields_survive_parsing_manager_input_and_persistence(
    tmp_path: Path,
    stance: str,
    view: str,
) -> None:
    provider = RawProtocolProvider(overrides={"stance": stance, "horizon_hours": 36})
    result, gateway = _run(provider)
    assert result.ok
    vote = next(v for v in result.votes if v.role == "technical")
    assert vote.analyst_stance == stance and vote.view == view
    assert vote.horizon_hours == 36
    assert vote.key_points == [
        "Observed reference price is 1.12.",
        "Inputs do not establish causal claims.",
    ]
    assert vote.target_position_pct == Decimal("0")  # Analysts cannot size an order.
    event = next(
        e for e in gateway.validation_records if e.call_id == vote.model_call_id
    )
    assert event.verdict == "accepted"
    assert event.parsed_output is not None and event.parsed_output["stance"] == stance
    assert set(event.parsed_output) == {
        "stance",
        "confidence",
        "horizon_hours",
        "key_points",
        "evidence_ids",
        "veto",
    }
    manager = provider.requests[-1]
    opinions = json.loads(
        manager.input_text.split("Earlier analyst votes (untrusted evidence):\n")[1]
    )
    assert len(opinions) == 4
    assert opinions[0]["stance"] == stance and opinions[0]["horizon_hours"] == 36
    assert opinions[0]["key_points"] == vote.key_points
    assert all(
        "target_position_pct" not in opinion and "suggested_action" not in opinion
        for opinion in opinions
    )
    store = AiTradingStore(db_path=tmp_path / "cycle.duckdb")
    record = DailyCycleRecord(
        cycle_id="native-analyst-cycle",
        trading_day="2026-10-02",
        symbols=["EUR_USD"],
        votes=result.votes,
        plans=[result.plan] if result.plan else [],
        outcome="skipped_no_intent",
        enabled=True,
        summary="Native analyst evidence",
        created_at=NOW,
    )
    store.save_cycle(record)
    store.close()
    reader = AiTradingStore(db_path=tmp_path / "cycle.duckdb")
    try:
        stored = reader.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["votes"][0]["analyst_stance"] == stance
        assert stored["votes"][0]["horizon_hours"] == 36
        assert stored["votes"][0]["key_points"] == vote.key_points
    finally:
        reader.close()


@pytest.mark.parametrize(
    "field",
    ["stance", "confidence", "horizon_hours", "key_points", "evidence_ids", "veto"],
)
def test_all_six_analyst_fields_are_required(field: str) -> None:
    result, gateway = _run(RawProtocolProvider(missing=field))
    assert result.plan is None
    assert not any(v.role == "technical" for v in result.votes)
    assert gateway.validation_records[0].verdict == "schema_rejected"


@pytest.mark.parametrize(
    "overrides",
    [
        {"stance": "bullish"},
        {"stance": None},
        {"confidence": "0.8"},
        {"confidence": True},
        {"confidence": 2},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"horizon_hours": "24"},
        {"horizon_hours": True},
        {"horizon_hours": 1.5},
        {"horizon_hours": 0},
        {"horizon_hours": -1},
        {"key_points": []},
        {"key_points": [""]},
        {"key_points": ["  "]},
        {"key_points": [1]},
        {"key_points": "summary"},
        {"veto": "false"},
        {"veto": 0},
        {"veto": None},
        {"suggested_action": "buy"},
        {"target_position_pct": "1"},
        {"analysis": "Old analyst field"},
        {"needs_human_review": False},
    ],
)
def test_invalid_types_values_and_old_fields_are_rejected(
    overrides: dict[str, Any],
) -> None:
    result, gateway = _run(RawProtocolProvider(overrides=overrides))
    assert result.plan is None
    assert gateway.validation_records[0].verdict == "schema_rejected"
    assert len(result.votes) == 4


def test_complete_old_format_is_rejected_or_repaired_through_the_same_new_schema() -> (
    None
):
    result, gateway = _run(RawProtocolProvider(legacy=True))
    assert (
        result.plan is None
        and gateway.validation_records[0].verdict == "schema_rejected"
    )
    provider = RawProtocolProvider(legacy=True)
    repaired, gateway = _run(provider, repairs=2)
    assert repaired.ok and len(repaired.votes) == 5
    assert len(provider.requests) == 6 and len(repaired.repair_attempts) == 1
    technical = next(v for v in repaired.votes if v.role == "technical")
    assert technical.analyst_stance == "long" and technical.horizon_hours == 24
    assert gateway.validation_records[0].verdict == "schema_rejected"
    assert gateway.validation_records[1].verdict == "accepted"
    assert gateway.validation_records[1].call_id == technical.model_call_id
    assert gateway.call_records[1].audit_payload is not None
    assert gateway.call_records[1].audit_payload["call_kind"] == "repair"
    assert '"horizon_hours"' in provider.requests[1].input_text
