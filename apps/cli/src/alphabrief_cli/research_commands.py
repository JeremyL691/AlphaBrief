"""CLI subcommands for the research module — Multi-Model Research Committee."""

from __future__ import annotations

import sys

import typer
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_research.orchestrator import DebateOrchestrator
from alphabrief_research.schemas import DebateQuestion

research_app = typer.Typer(help="Run and inspect AI research debates.")


@research_app.command("debate")
def debate_cmd(
    question: str = typer.Argument(
        ...,
        help="The research question for multi-model debate.",
    ),
    symbol: str | None = typer.Option(
        None,
        "--symbol",
        help="Symbol to analyze (optional).",
    ),
    time_horizon: str | None = typer.Option(
        None,
        "--time-horizon",
        help="Analysis time horizon (e.g. '5 trading days').",
    ),
    perspectives: str | None = typer.Option(
        None,
        "--perspectives",
        help="Comma-separated perspectives: technical,fundamental,risk,judge",
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        help="Additional context for the analysis.",
    ),
) -> None:
    """Run a multi-model research debate via DebateOrchestrator.

    Routes the question to multiple AI perspectives and prints
    individual responses and the aggregated consensus.
    """
    try:
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-debate",
            capabilities=["structured_output"],
            structured_output={
                "analysis": "Sample analysis from fake provider.",
                "view": "neutral",
                "confidence": 0.7,
                "evidence": ["Sample evidence point"],
                "risks": ["Sample risk factor"],
                "suggested_action": "watch",
                "needs_human_review": True,
            },
        )
        gateway = ModelGateway([provider])

        parsed_perspectives: list[str] = []
        if perspectives:
            parsed_perspectives = [
                p.strip() for p in perspectives.split(",") if p.strip()
            ]
        if not parsed_perspectives:
            parsed_perspectives = ["technical", "fundamental", "risk", "judge"]

        debate_question = DebateQuestion(
            question=question,
            symbol=symbol,
            time_horizon=time_horizon,
            perspectives=parsed_perspectives,
            context=context,
        )
        orchestrator = DebateOrchestrator(gateway)
        result = orchestrator.debate(debate_question)

    except Exception as exc:
        print(f"error: research debate failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not result.ok or result.record is None:
        msg = result.error_message or "unknown error"
        print(f"research debate failed: {msg}", file=sys.stderr)
        sys.exit(1)

    record = result.record

    print(f"Debate ID: {record.debate_id}")
    print(f"Question: {question}")
    if symbol:
        print(f"Symbol: {symbol}")
    print(f"Perspectives: {', '.join(record.question.perspectives)}")
    print()

    for _i, resp in enumerate(record.responses, 1):
        print(f"--- Perspective: {resp.perspective} ---")
        print(f"  model_name:   {resp.model_name}")
        print(f"  view:         {resp.view}")
        print(f"  confidence:   {resp.confidence}")
        print(f"  analysis:     {resp.analysis[:200]}...")
        print(f"  evidence:     {resp.evidence}")
        print(f"  risks:        {resp.risks}")
        print(f"  suggested:    {resp.suggested_action}")
        print()

    if record.consensus:
        consensus = record.consensus
        print("--- Consensus ---")
        print(f"  models:        {consensus.num_models}")
        print(f"  agreement:     {consensus.agreement_level}")
        print(f"  consensus_view: {consensus.consensus_view}")
        print(f"  avg_confidence: {consensus.avg_confidence}")
        print(f"  distribution:  {consensus.view_distribution}")
        print(f"  key_evidence:  {consensus.key_evidence}")
        print(f"  key_risks:     {consensus.key_risks}")
        print(f"  disagreements: {consensus.disagreements}")
        print(f"  suggested:     {consensus.suggested_action}")


__all__ = ["research_app"]
