"""Research brief routes — generate and retrieve DailyAlphaBriefs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from alphabrief_models import (
    DailyAlphaBrief,
    FakeProviderAdapter,
    ModelGateway,
    generate_daily_alpha_brief,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# In-memory brief store
# ---------------------------------------------------------------------------

_brief_store: dict[str, DailyAlphaBrief] = {}


def _clear_briefs() -> None:
    """Clear the in-memory brief store (for test isolation)."""
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
    result = generate_daily_alpha_brief(
        gateway,
        input_text=body.input_text,
        prompt_version=body.prompt_version,
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

    _brief_store[brief_id] = brief
    return brief.model_dump(mode="json")


@router.get("/history", response_model=BriefHistoryResponse)
def list_brief_history() -> BriefHistoryResponse:
    """List all generated daily brief summaries."""
    summaries = [
        BriefSummary(
            brief_id=b.brief_id,
            trading_day=b.trading_day.isoformat(),
            generated_at=b.generated_at.isoformat(),
            headline=b.headline,
        )
        for b in _brief_store.values()
    ]
    return BriefHistoryResponse(briefs=summaries)


@router.get("/{brief_id}")
def get_brief(brief_id: str) -> dict[str, object]:
    """Retrieve a single complete brief by ID."""
    brief = _brief_store.get(brief_id)
    if brief is None:
        raise HTTPException(
            status_code=404, detail=f"brief {brief_id!r} not found"
        )
    return brief.model_dump(mode="json")


__all__ = [
    "BriefGenerateRequest",
    "BriefHistoryResponse",
    "BriefSummary",
    "router",
]
