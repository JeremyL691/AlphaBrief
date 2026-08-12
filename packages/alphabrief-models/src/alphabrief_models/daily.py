"""Daily AlphaBrief generation through the ModelGateway."""

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from alphabrief_models.briefs import (
    DailyAlphaBrief,
    MarketBrief,
    SymbolBrief,
    SymbolVerdict,
)
from alphabrief_models.gateway import (
    ModelCallRecord,
    ModelCapability,
    ModelGateway,
    ModelRequest,
)
from alphabrief_models.structured_output import (
    StructuredOutputErrorCode,
    parse_structured_output,
)


class DailyBriefGenerationErrorCode(StrEnum):
    """Stable error codes for daily brief generation failures."""

    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_FAILED = "provider_failed"
    STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"


class DailyBriefGenerationResult(BaseModel):
    """Result of a DailyAlphaBrief generation attempt."""

    model_config = ConfigDict(extra="forbid")

    brief: DailyAlphaBrief | None = None
    ok: bool = False
    record: ModelCallRecord
    error_code: DailyBriefGenerationErrorCode | None = None
    structured_error_code: StructuredOutputErrorCode | None = None
    error_message: str | None = None


def generate_daily_alpha_brief(
    gateway: ModelGateway,
    *,
    input_text: str,
    prompt_version: str,
    request_id: str | None = None,
    required_capabilities: Sequence[ModelCapability] = ("structured_output",),
    metadata: dict[str, str] | None = None,
) -> DailyBriefGenerationResult:
    """Generate and validate a DailyAlphaBrief through ModelGateway."""

    request = ModelRequest(
        request_id=request_id or f"daily_brief_{uuid4().hex}",
        task_type="daily_brief",
        prompt_version=prompt_version,
        input_text=input_text,
        required_capabilities=list(required_capabilities),
        metadata=metadata or {},
    )
    gateway_result = gateway.invoke(request)

    if gateway_result.response is None:
        return DailyBriefGenerationResult(
            brief=None,
            ok=False,
            record=gateway_result.record,
            error_code=_generation_error_code(gateway_result.record),
            structured_error_code=None,
            error_message=gateway_result.record.error_type,
        )

    parsed = parse_structured_output(
        gateway_result.response,
        target=DailyAlphaBrief,
    )
    if not parsed.ok:
        return DailyBriefGenerationResult(
            brief=None,
            ok=False,
            record=gateway_result.record,
            error_code=DailyBriefGenerationErrorCode.STRUCTURED_OUTPUT_INVALID,
            structured_error_code=parsed.error_code,
            error_message=parsed.error_message,
        )

    return DailyBriefGenerationResult(
        brief=parsed.parsed,
        ok=True,
        record=gateway_result.record,
        error_code=None,
        structured_error_code=None,
        error_message=None,
    )


def _generation_error_code(
    record: ModelCallRecord,
) -> DailyBriefGenerationErrorCode:
    if record.status == "rejected":
        return DailyBriefGenerationErrorCode.PROVIDER_REJECTED
    return DailyBriefGenerationErrorCode.PROVIDER_FAILED


def coerce_daily_brief(
    raw_output: str,
    *,
    trading_day: str,
    universe: Sequence[str] = (),
) -> DailyAlphaBrief | None:
    """Build a usable DailyAlphaBrief from raw model output.

    Real providers frequently deviate from the strict brief schema
    (extra/missing fields, renamed keys). Strict parsing is preferred;
    this coercion is the last-resort fallback that maps whatever JSON
    the model produced onto the schema so the daily brief surface never
    stays empty. Returns ``None`` when the output is not JSON at all.
    """
    try:
        data = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    def _text(*keys: str, default: str = "") -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return default

    def _string_list(*keys: str) -> list[str]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                cleaned = [
                    str(item).strip()
                    for item in value
                    if str(item).strip()
                ]
                if cleaned:
                    return cleaned
        return []

    now = datetime.now(UTC)
    market = data.get("market_brief")
    regime: Literal["bullish", "bearish", "neutral", "uncertain"] = "neutral"
    market_summary = _text("executive_summary", default="Markets were quiet.")
    market_confidence = 0.5
    market_key_factors: list[str] = []
    if isinstance(market, dict):
        raw_regime = str(market.get("regime", "")).lower()
        if raw_regime in {"bullish", "bearish", "neutral", "uncertain"}:
            regime = cast(
                Literal["bullish", "bearish", "neutral", "uncertain"],
                raw_regime,
            )
        market_summary = (
            _text("summary") or market_summary
        )
        try:
            market_confidence = float(market.get("confidence", 0.5))
        except (TypeError, ValueError):
            market_confidence = 0.5
        market_key_factors = _string_list("key_factors")

    symbol_briefs: list[SymbolBrief] = []
    raw_symbols = data.get("symbol_briefs")
    if isinstance(raw_symbols, list):
        for entry in raw_symbols:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("symbol") or "").strip()
            if not symbol:
                continue
            raw_direction = str(entry.get("direction", "")).lower()
            if raw_direction not in {"bullish", "bearish", "neutral"}:
                raw_direction = "neutral"
            direction: Literal["bullish", "bearish", "neutral"] = cast(
                Literal["bullish", "bearish", "neutral"], raw_direction
            )
            try:
                confidence = float(entry.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            rationale = str(
                entry.get("rationale") or entry.get("commentary") or ""
            ).strip() or f"{symbol} outlook."
            symbol_briefs.append(
                SymbolBrief(
                    brief_id=f"sb_{symbol.lower()}",
                    symbol=symbol,
                    generated_at=now,
                    horizon="1d",
                    verdict=SymbolVerdict(
                        direction=direction,
                        confidence=confidence,
                        rationale=rationale,
                    ),
                    catalysts=_string_list("catalysts"),
                    risks=_string_list("risks"),
                )
            )

    watchlist = _string_list("watchlist") or list(universe)
    risk_notes = _string_list("risk_notes") or ["Monitor positions closely."]

    return DailyAlphaBrief(
        brief_id=(
            _text("brief_id", default="")
            or f"brief_{now.strftime('%Y%m%d%H%M%S')}"
        ),
        generated_at=now,
        trading_day=cast(date, _text("trading_day", default=trading_day)),
        headline=(
            _text("headline")
            or f"Daily brief for {trading_day} — no clear edge."
        ),
        executive_summary=(
            _text("executive_summary")
            or "Model output was captured but did not validate strictly."
        ),
        market_brief=MarketBrief(
            brief_id=f"mb_{now.strftime('%Y%m%d%H%M%S')}",
            generated_at=now,
            trading_day=cast(date, trading_day),
            regime=regime,
            summary=market_summary,
            confidence=market_confidence,
            key_factors=market_key_factors,
        ),
        symbol_briefs=symbol_briefs,
        watchlist=watchlist,
        risk_notes=risk_notes,
        news_and_macro_summary=(
            _text("news_and_macro_summary")
            or _text("news_summary")
            or None
        ),
        sentiment_summary=_text("sentiment_summary") or None,
        news_driven_watchlist=_string_list("news_driven_watchlist") or None,
        risk_officer_notes=_text("risk_officer_notes") or None,
    )
