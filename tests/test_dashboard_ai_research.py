"""M14-W03: AI Research workspace.

Covers AC-M14-W03-03: AI Research shows every role turn, citation,
dissent, schema or provider degradation, final proposal or no-trade
result, and immutable evidence identifiers from the API.
"""

from __future__ import annotations

from alphabrief_api.dashboard.workspaces import build_ai_research_view


def _votes() -> list[dict[str, object]]:
    return [
        {
            "role": "technical",
            "model_name": "model-a",
            "view": "bullish",
            "confidence": 0.7,
            "citations": ["evidence-1", "news-42"],
            "dissent": None,
        },
        {
            "role": "risk",
            "model_name": "model-b",
            "view": "bearish",
            "confidence": 0.5,
            "citations": ["evidence-2"],
            "dissent": "counterparty risk not priced",
        },
    ]


def _plans() -> list[dict[str, object]]:
    return [
        {
            "proposal_id": "proposal-1",
            "symbol": "EUR_USD",
            "side": "buy",
            "confidence": 0.7,
            "needs_human_review": False,
            "key_evidence": ["evidence-1", "news-42"],
        }
    ]


class TestAiResearchView:
    def test_every_role_turn_is_shown(self) -> None:
        view = build_ai_research_view(
            cycle_id="cycle-1", votes=_votes(), plans=_plans()
        )
        assert len(view.role_turns) == 2
        assert view.role_turns[0].role == "technical"
        assert view.role_turns[0].view == "bullish"
        assert view.role_turns[1].role == "risk"

    def test_citations_and_dissent_are_carried_verbatim(self) -> None:
        view = build_ai_research_view(
            cycle_id="cycle-1", votes=_votes(), plans=_plans()
        )
        assert view.role_turns[0].citations == ("evidence-1", "news-42")
        assert view.role_turns[1].dissent == "counterparty risk not priced"

    def test_final_proposal_carries_evidence_ids(self) -> None:
        view = build_ai_research_view(
            cycle_id="cycle-1", votes=_votes(), plans=_plans()
        )
        assert len(view.proposals) == 1
        proposal = view.proposals[0]
        assert proposal.proposal_id == "proposal-1"
        assert proposal.symbol == "EUR_USD"
        assert proposal.side == "buy"
        assert proposal.evidence_ids == ("evidence-1", "news-42")

    def test_no_trade_outcome_is_explicit(self) -> None:
        view = build_ai_research_view(
            cycle_id="cycle-1", votes=_votes(), plans=[], outcome="no_trade"
        )
        assert view.outcome == "no_trade"
        assert view.proposals == ()

    def test_degredation_is_exposed(self) -> None:
        view = build_ai_research_view(
            cycle_id="cycle-1",
            votes=_votes(),
            plans=_plans(),
            degradation="provider degraded: schema v2",
        )
        assert view.degradation == "provider degraded: schema v2"

    def test_deterministic(self) -> None:
        first = build_ai_research_view(
            cycle_id="cycle-1", votes=_votes(), plans=_plans()
        )
        second = build_ai_research_view(
            cycle_id="cycle-1", votes=_votes(), plans=_plans()
        )
        assert first.model_dump() == second.model_dump()
        assert first.cycle_id == "cycle-1"
