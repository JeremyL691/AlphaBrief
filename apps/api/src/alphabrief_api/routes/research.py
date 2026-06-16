"""AlphaBrief research API routes — Multi-Model Research Committee.

Phase 8: Routes for running multi-model research debates and retrieving
past debate records. Uses ``DebateOrchestrator`` with ``FakeProviderAdapter``
for development/testing and ``DebateStore`` for DuckDB persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_research import ResearchContextBuilder
from alphabrief_research.orchestrator import DebateOrchestrator
from alphabrief_research.schemas import DebateQuestion
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db import MacroStore, NewsStore
from alphabrief_api.db.debates import DebateStore

# ---------------------------------------------------------------------------
# Persistent debate store (DuckDB-backed)
# ---------------------------------------------------------------------------

_debate_store: DebateStore | None = None


def _get_debate_store() -> DebateStore:
    """Return the singleton DebateStore, creating it on first access."""
    global _debate_store
    if _debate_store is None:
        _debate_store = DebateStore()
    return _debate_store


def _clear_debate_store() -> None:
    """Clear the persistent debate store (for test isolation)."""
    global _debate_store
    if _debate_store is not None:
        _debate_store.clear()


# ---------------------------------------------------------------------------
# Model gateway (testable via FakeProvider)
# ---------------------------------------------------------------------------

_gateway: ModelGateway | None = None


def _get_gateway() -> ModelGateway:
    """Return a shared ModelGateway with a FakeProvider for debate."""
    global _gateway
    if _gateway is None:
        _sample_response = {
            "analysis": (
                "The market shows positive momentum driven by strong Q2 "
                "earnings and improving macroeconomic indicators."
            ),
            "view": "bullish",
            "confidence": 0.82,
            "evidence": [
                "Q2 earnings beat estimates across major sectors",
                "CPI data showing downward trend in inflation",
                "Fed signaling potential rate cuts in H2",
            ],
            "risks": [
                "Geopolitical tensions in Eastern Europe",
                "Consumer debt levels near all-time highs",
            ],
            "suggested_action": "watch",
            "needs_human_review": True,
        }
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-debate",
            capabilities=["structured_output"],
            structured_output=_sample_response,
        )
        _gateway = ModelGateway(providers=[provider])
    return _gateway


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class DebateRequest(BaseModel):
    """Request body for POST /api/v1/research/debate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str = Field(min_length=1)
    symbol: str | None = None
    time_horizon: str | None = None
    perspectives: list[str] | None = None
    context: str | None = None
    include_news: bool = Field(
        default=False,
        description="Include news context in the debate prompt.",
    )
    include_macro: bool = Field(
        default=False,
        description="Include macro context in the debate prompt.",
    )
    news_symbols: list[str] | None = Field(
        default=None,
        description="Symbols to filter news for.",
    )
    macro_indicators: list[str] | None = Field(
        default=None,
        description="Macro indicator series to include.",
    )


class DebateSummary(BaseModel):
    """Summary of a debate for the history list."""

    model_config = ConfigDict(frozen=True)

    debate_id: str
    question: str
    created_at: str


class DebateHistoryResponse(BaseModel):
    """Response body for GET /api/v1/research/debate."""

    model_config = ConfigDict(frozen=True)

    debates: list[DebateSummary]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/research", tags=["research"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/debate", status_code=201)
def create_debate(body: DebateRequest) -> dict[str, object]:
    """Run a multi-model research debate and persist the result."""
    gateway = _get_gateway()

    news_context: str | None = None
    macro_context: str | None = None
    if body.include_news or body.include_macro:
        builder = _build_research_context_builder()
        end = datetime.now(UTC)
        start = end - timedelta(days=7)
        if body.include_news:
            symbols = body.news_symbols or ([body.symbol] if body.symbol else [])
            news_context = builder.build_news_context(
                symbols, start, end, limit=20
            )
        if body.include_macro:
            indicators = body.macro_indicators or []
            if indicators:
                macro_context = builder.build_macro_context(
                    indicators, start, end
                )

    question = DebateQuestion(
        question=body.question,
        symbol=body.symbol,
        time_horizon=body.time_horizon,
        perspectives=body.perspectives or ["technical", "fundamental", "risk", "judge"],
        context=body.context,
        news_context=news_context,
        macro_context=macro_context,
    )
    orchestrator = DebateOrchestrator(gateway)
    result = orchestrator.debate(question)

    if not result.ok or result.record is None:
        raise HTTPException(
            status_code=422,
            detail=f"debate failed: {result.error_message or 'unknown error'}",
        )

    store = _get_debate_store()
    saved_id = store.save_debate_record(
        question=result.record.question.model_dump(mode="json"),
        responses=[r.model_dump(mode="json") for r in result.record.responses],
        consensus=(
            result.record.consensus.model_dump(mode="json")
            if result.record.consensus
            else {}
        ),
    )

    return {
        "debate_id": saved_id,
        "question": result.record.question.model_dump(mode="json"),
        "responses": [r.model_dump(mode="json") for r in result.record.responses],
        "consensus": (
            result.record.consensus.model_dump(mode="json")
            if result.record.consensus
            else None
        ),
    }


@router.get("/debate", response_model=DebateHistoryResponse)
def list_debates() -> DebateHistoryResponse:
    """List all debate records."""
    store = _get_debate_store()
    records = store.list_debate_records()
    summaries = [
        DebateSummary(
            debate_id=r["id"],
            question=(
                r["question"].get("question", str(r["question"]))
                if isinstance(r["question"], dict)
                else str(r["question"])
            ),
            created_at=r["created_at"],
        )
        for r in records
    ]
    return DebateHistoryResponse(debates=summaries)


@router.get("/debate/{debate_id}")
def get_debate(debate_id: str) -> dict[str, object]:
    """Retrieve a single debate record by ID."""
    store = _get_debate_store()
    record = store.get_debate_record(debate_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"debate {debate_id!r} not found"
        )
    return record


__all__ = [
    "DebateHistoryResponse",
    "DebateRequest",
    "DebateSummary",
    "_clear_debate_store",
    "router",
]


def _build_research_context_builder() -> ResearchContextBuilder:
    """Build a ResearchContextBuilder wired to NewsStore/MacroStore."""
    from alphabrief_news import MacroIndicator, NewsHeadline

    news_store = NewsStore()
    macro_store = MacroStore()

    def news_loader(
        symbols: list[str], start: datetime, end: datetime, limit: int,
    ) -> list[NewsHeadline]:
        try:
            rows = news_store.list_headlines(
                symbol=symbols[0] if symbols else None,
                start=start,
                end=end,
                limit=limit,
            )
            return list(rows)
        except Exception:
            return []

    def macro_loader(
        indicators: list[str], start: datetime, end: datetime,
    ) -> list[MacroIndicator]:
        if not indicators:
            return []
        try:
            all_rows: list[MacroIndicator] = []
            for ind_id in indicators:
                rows = macro_store.list_indicators(
                    indicator_id=ind_id,
                    start=start,
                    end=end,
                    limit=20,
                )
                all_rows.extend(rows)
            return all_rows
        except Exception:
            return []

    return ResearchContextBuilder(
        news_loader=news_loader, macro_loader=macro_loader
    )
