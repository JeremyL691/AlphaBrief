"""The FX committee has one canonical role set and read-only historical identities."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from alphabrief_models import ModelGateway
from alphabrief_news import NewsHeadline
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.committee_prompts import (
    PROMPT_VERSION,
    build_committee_prompt,
    default_roles,
)
from alphabrief_trader.rules import DisciplineGate
from alphabrief_trader.schemas import (
    CommitteeInput,
    CommitteeRole,
    CommitteeVote,
    MarketSnapshot,
    SignalInputEvidence,
    SignalMarketEvidence,
)
from committee_provider import GroundedProvider

ROLES = ["technical", "macro_news", "intermarket", "risk", "manager"]
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EUR_USD",
        reference_price=Decimal("1.12"),
        captured_at=NOW,
        news_items=[
            NewsHeadline(
                headline_id="central-bank-news",
                symbols=["EUR_USD"],
                published_at=NOW,
                source="central-bank-feed",
                category="macro",
                title="Relative policy expectations changed",
            )
        ],
        macro_context="Actual inflation publication: 2.1 percent",
        signal_evidence=SignalInputEvidence(
            observed_at=NOW,
            signals={
                "XAU_USD": SignalMarketEvidence(
                    h1_return_pct=Decimal("0.4"),
                    daily_return_pct=Decimal("0.7"),
                    correlation_20d=Decimal("-0.25"),
                    correlation_samples=20,
                    correlation_input_hash="actual-aligned-window",
                ),
            },
            excluded={"SPX500_USD": "broker_not_found"},
        ),
    )


def _vote(role: str) -> CommitteeVote:
    return CommitteeVote.model_validate(
        {
            "role": role,
            "model_name": "historical-model",
            "analysis": "Stored judgment",
            "view": "bullish",
            "confidence": 0.8,
            "evidence": [],
            "risks": [],
            "suggested_action": "buy",
            "target_position_pct": Decimal("0.1"),
            "created_at": NOW,
        }
    )


def test_one_canonical_default_role_order() -> None:
    assert default_roles() == ROLES
    assert CommitteeInput(snapshot=_snapshot()).roles == ROLES
    assert PROMPT_VERSION == "aitrader-roles-v4"


@pytest.mark.parametrize("legacy", ["news_sentiment", "fundamental"])
def test_historical_roles_are_preserved_but_cannot_generate_new_plans(
    legacy: str,
) -> None:
    historical = _vote(legacy)
    assert historical.role == legacy
    assert historical.model_dump()["role"] == legacy
    with pytest.raises(ValueError):
        CommitteeInput.model_validate({"snapshot": _snapshot(), "roles": [legacy]})
    with pytest.raises(ValueError, match="read-only"):
        DisciplineGate().synthesize(
            symbol="EUR_USD",
            manager_vote=_vote("manager"),
            analyst_votes=[historical],
        )
    with pytest.raises(ValueError, match="unknown committee role"):
        TradingCommittee(
            gateway=ModelGateway([]), roles=cast(list[CommitteeRole], [legacy])
        )


def test_manager_cannot_run_before_analysts() -> None:
    with pytest.raises(ValueError, match="run last"):
        CommitteeInput.model_validate(
            {
                "snapshot": _snapshot(),
                "roles": ["manager", "technical"],
            }
        )


def test_fx_macro_and_intermarket_prompts_use_actual_distinct_evidence() -> None:
    payload = CommitteeInput(snapshot=_snapshot())
    macro = build_committee_prompt("macro_news", payload)
    intermarket = build_committee_prompt("intermarket", payload)
    assert "基准货币相对报价货币" in macro
    assert "不能编造数据" in macro
    assert "XAU_USD" in intermarket and "H1/D收益" in intermarket
    assert "相关性不代表因果" in intermarket
    assert "信号品种只读" in intermarket
    for key, body in payload.evidence_catalog.items():
        assert f"{key}: {body}" in macro and f"{key}: {body}" in intermarket
    assert any(
        '"correlation_20d":"-0.25"' in body
        for body in payload.evidence_catalog.values()
    )
    assert not any(
        '"instrument":"SPX500_USD"' in body
        for body in payload.evidence_catalog.values()
    )


def test_explicit_constructor_roles_are_used_when_input_has_no_override() -> None:
    requests: list[Any] = []

    class RecordingProvider(GroundedProvider):
        def call(self, request: Any) -> Any:
            requests.append(request)
            response = super().call(request)
            if request.metadata.get("phase") == "summary":
                output = response.structured_output
                assert output is not None
                response = response.model_copy(
                    update={
                        "structured_output": {
                            "analysis": output["analysis"],
                            "view": output["view"],
                            "confidence": output["confidence"],
                            "evidence_ids": output["evidence_ids"],
                            "stance": "agreement",
                        }
                    }
                )
            return response

    provider = RecordingProvider(
        capabilities=["structured_output"],
        structured_output={
            "analysis": "No supported direction.",
            "view": "neutral",
            "confidence": 0.8,
            "evidence_ids": ["input-evidence"],
            "risks": [],
            "suggested_action": "hold",
            "target_position_pct": "0",
            "veto": False,
            "needs_human_review": False,
        },
    )
    committee = TradingCommittee(
        gateway=ModelGateway([provider]),
        roles=["macro_news", "manager"],
        max_turns=5,
        challenge_rounds=0,
    )
    result = committee.run(CommitteeInput(snapshot=_snapshot()))
    assert result.ok
    assert [r.metadata["committee_role"] for r in requests] == [
        "macro_news",
        "manager",
        "manager",
    ]
    assert result.transcript is not None
    assert [(turn.phase, turn.role) for turn in result.transcript.turns] == [
        ("opening", "macro_news"),
        ("opening", "manager"),
        ("summary", "manager"),
    ]
    assert '"role": "macro_news"' in requests[1].input_text
    requests.clear()
    result = committee.run(
        CommitteeInput(snapshot=_snapshot(), roles=["risk", "manager"])
    )
    assert result.ok
    assert [r.metadata["committee_role"] for r in requests] == [
        "risk",
        "manager",
        "manager",
    ]
    assert result.transcript is not None
    assert [(turn.phase, turn.role) for turn in result.transcript.turns] == [
        ("opening", "risk"),
        ("opening", "manager"),
        ("summary", "manager"),
    ]
    assert '"role": "risk"' in requests[1].input_text
