"""Research brief routes — generate and retrieve DailyAlphaBriefs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    generate_daily_alpha_brief,
    render_brief_prompt_v2,
)
from alphabrief_research import ResearchContextBuilder
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db import BriefStore, MacroStore, NewsStore

# ---------------------------------------------------------------------------
# Persistent brief store (DuckDB-backed)
# ---------------------------------------------------------------------------

_brief_store: BriefStore | None = None


def _get_brief_store() -> BriefStore:
    """Return the singleton BriefStore, creating it on first access."""
    global _brief_store
    if _brief_store is None:
        _brief_store = BriefStore()
    return _brief_store


def _clear_brief_store() -> None:
    """Clear the persistent brief store (for test isolation)."""
    global _brief_store
    if _brief_store is not None:
        _brief_store.clear()


# ---------------------------------------------------------------------------
# Model gateway (testable via FakeProvider)
# ---------------------------------------------------------------------------

_gateway: ModelGateway | None = None


def _get_gateway() -> ModelGateway:
    """Return a shared ModelGateway with a FakeProvider."""
    global _gateway
    if _gateway is None:
        _now = datetime.now(UTC)
        _today = _now.date()
        _sample_brief_dict = {
            "brief_id": "brief_sample",
            "generated_at": _now.isoformat(),
            "trading_day": _today.isoformat(),
            "headline": "Market outlook is positive",
            "executive_summary": "Markets show strength across key sectors.",
            "market_brief": {
                "brief_id": "mkt_sample",
                "generated_at": _now.isoformat(),
                "trading_day": _today.isoformat(),
                "regime": "bullish",
                "summary": "Bullish momentum continues.",
                "confidence": 0.85,
                "key_factors": ["Earnings", "Rate outlook"],
            },
            "symbol_briefs": [
                {
                    "brief_id": "sym_sample",
                    "symbol": "SPY",
                    "generated_at": _now.isoformat(),
                    "horizon": "1d",
                    "verdict": {
                        "direction": "bullish",
                        "confidence": 0.8,
                        "rationale": "Positive momentum.",
                    },
                    "catalysts": ["Earnings beat"],
                    "risks": ["Valuation concern"],
                }
            ],
            "watchlist": ["SPY", "QQQ"],
            "risk_notes": ["Monitor volatility"],
        }
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-brief",
            capabilities=["structured_output"],
            structured_output=_sample_brief_dict,
        )
        _gateway = ModelGateway(providers=[provider])
    return _gateway


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class BriefGenerateRequest(BaseModel):
    """Request body for POST /api/v1/brief/generate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_text: str = Field(
        default="Generate a daily alpha brief for today.",
        min_length=1,
    )
    prompt_version: str = "brief_v1:1"
    include_news: bool = Field(
        default=False,
        description="Include news context in the prompt.",
    )
    include_macro: bool = Field(
        default=False,
        description="Include macro context in the prompt.",
    )
    news_symbols: list[str] | None = Field(
        default=None,
        description="Symbols to filter news for (default: empty = general).",
    )
    macro_indicators: list[str] | None = Field(
        default=None,
        description="Macro indicator series to include.",
    )


class BriefSummary(BaseModel):
    """Summary of a generated brief for the history list."""

    model_config = ConfigDict(frozen=True)

    brief_id: str
    trading_day: str
    generated_at: str
    headline: str


class BriefHistoryResponse(BaseModel):
    """Response body for GET /api/v1/brief/history."""

    model_config = ConfigDict(frozen=True)

    briefs: list[BriefSummary]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/brief", tags=["brief"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/generate", status_code=201)
def generate_brief(body: BriefGenerateRequest) -> dict[str, object]:
    """Generate a DailyAlphaBrief through ModelGateway."""
    gateway = _get_gateway()

    news_context = ""
    macro_context = ""
    watchlist_hint = ""
    if body.include_news or body.include_macro:
        builder = _build_research_context_builder()
        end = datetime.now(UTC)
        start = end - timedelta(days=7)
        symbols = body.news_symbols or []
        if body.include_news:
            news_context = builder.build_news_context(
                symbols, start, end, limit=20
            )
        else:
            news_context = "(news context disabled)"
        if symbols:
            watchlist_hint = (
                "Candidate symbols from caller: " + ", ".join(symbols) + "."
            )
        indicators = body.macro_indicators or []
        if body.include_macro and indicators:
            macro_context = builder.build_macro_context(indicators, start, end)
        else:
            macro_context = "(macro context disabled)"

    if body.prompt_version.endswith("v2") or body.include_news or body.include_macro:
        try:
            rendered = render_brief_prompt_v2(
                "daily_alpha_brief",
                "v2",
                {
                    "trading_day": datetime.now(UTC).date().isoformat(),
                    "market_data_context": body.input_text,
                    "news_context": news_context,
                    "macro_context": macro_context,
                    "sentiment_summary": watchlist_hint,
                },
            )
            input_text = rendered.input_text
            prompt_version = rendered.prompt_version
        except Exception:
            input_text = body.input_text
            prompt_version = body.prompt_version
    else:
        input_text = body.input_text
        prompt_version = body.prompt_version

    result = generate_daily_alpha_brief(
        gateway,
        input_text=input_text,
        prompt_version=prompt_version,
    )

    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail=(
                f"brief generation failed: {result.error_code or 'unknown'} — "
                f"{result.error_message or 'no detail'}"
            ),
        )

    brief = result.brief
    assert brief is not None

    brief_id = brief.brief_id
    if not brief_id or brief_id == "brief_sample":
        brief_id = f"brief_{uuid4().hex[:12]}"
        brief = brief.model_copy(update={"brief_id": brief_id})

    store = _get_brief_store()
    brief_dict = brief.model_dump(mode="json")
    store.save_brief(brief_dict, brief_id=brief_id)
    return brief_dict


def _build_research_context_builder() -> ResearchContextBuilder:
    """Build a ResearchContextBuilder wired to the current NewsStore/MacroStore."""
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


@router.get("/history", response_model=BriefHistoryResponse)
def list_brief_history() -> BriefHistoryResponse:
    """List all generated daily brief summaries."""
    store = _get_brief_store()
    summaries = [
        BriefSummary(
            brief_id=b["id"],
            trading_day=b["trading_day"],
            generated_at=b["created_at"],
            headline=b["headline"],
        )
        for b in store.list_briefs()
    ]
    return BriefHistoryResponse(briefs=summaries)


@router.get("/{brief_id}")
def get_brief(brief_id: str) -> dict[str, object]:
    """Retrieve a single complete brief by ID."""
    store = _get_brief_store()
    result = store.get_brief(brief_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"brief {brief_id!r} not found"
        )
    return result["brief"]  # type: ignore[no-any-return]


__all__ = [
    "BriefGenerateRequest",
    "BriefHistoryResponse",
    "BriefSummary",
    "_clear_brief_store",
    "router",
]
