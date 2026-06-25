"""Risk routes — config, dashboard, and news/macro context.

The routes in this module are strictly **read-only**. They never
modify the risk gate, never place orders, and never call
ModelGateway. The news/macro context endpoint surfaces a
:class:`alphabrief_research.ResearchContextSummary` together with the
corresponding :class:`alphabrief_risk.RiskContextDecision` so the user
can see how external evidence would tighten (never relax) risk
treatment, but the actual risk limits remain owned by
:class:`alphabrief_risk.RiskGate`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from alphabrief_core import OrderIntent, load_paper_execution_policy, load_settings
from alphabrief_research import (
    ResearchContextSummary,
    build_structured_summary,
)
from alphabrief_risk import (
    AccountExposureContext,
    KillSwitch,
    RiskContextDecision,
    RiskGate,
    RiskLimitConfig,
    evaluate_news_macro_risk,
)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.routes.macro import _get_store as _get_macro_store
from alphabrief_api.routes.news import _get_store as _get_news_store

# ---------------------------------------------------------------------------
# Module-level risk gate (runtime config — stays in-memory)
# ---------------------------------------------------------------------------

_execution_policy = load_paper_execution_policy(load_settings().execution_policy_file)
_default_limits = RiskLimitConfig(
    trading_enabled=True,
    live_trading_enabled=False,
    enabled_strategies=frozenset(),
    symbol_allowlist=frozenset(_execution_policy.symbols),
    max_order_value=_execution_policy.max_order_notional,
    max_order_quantity=None,
    # Phase 19: pull the runtime account-exposure cap straight from the
    # reviewed PaperExecutionPolicy. This is the single point that turns
    # the static $300 boundary into a live RiskGate check.
    max_total_exposure=_execution_policy.max_total_exposure,
    require_data_quality_passed=True,
    require_human_review=_execution_policy.require_human_review,
    # R21.2: account-level stateless rules. Per-symbol exposure cap is
    # set above the per-order notional so a single symbol cannot
    # accumulate beyond it; concentration is a no-op while the allowlist
    # is single-symbol (paper MVP); leverage is 1.0 (long-only, no
    # margin); price deviation, signal staleness and duplicate-order
    # detection use tight paper defaults. ``require_market_open`` stays
    # off by default so the paper workbench allows manual out-of-session
    # test orders; the automated scheduler path is the place to enforce
    # the session. All tighten-only / fail-closed; ``None``/``False``
    # preserves legacy behavior for any a caller does not configure.
    max_symbol_exposure=_execution_policy.max_total_exposure,
    max_concentration_pct=Decimal("1.0"),
    max_leverage=Decimal("1.0"),
    max_price_deviation_pct=Decimal("0.05"),
    max_signal_age_seconds=300,
    require_market_open=False,
    session_policy=_execution_policy,
    duplicate_order_window_seconds=30,
    duplicate_order_max_count=1,
    # R21.3: stateful account rules. Paper defaults are 5% daily loss
    # and 10% drawdown. The paper route injects ``equity_high_water_mark``
    # and ``day_start_equity`` from the persistent equity-snapshot store
    # so these caps remain tighten-only across restarts.
    max_daily_loss_pct=Decimal("0.05"),
    max_drawdown_floor_pct=Decimal("0.10"),
)
_default_kill_switch = KillSwitch()
_default_risk_gate = RiskGate(limits=_default_limits, kill_switch=_default_kill_switch)


def _get_risk_gate() -> RiskGate:
    return _default_risk_gate


def _reset_risk_gate(limits: RiskLimitConfig | None = None) -> None:
    """Reset risk gate state for test isolation."""
    global _default_kill_switch, _default_risk_gate
    _default_kill_switch = KillSwitch()
    _default_risk_gate = RiskGate(
        limits=_default_limits if limits is None else limits,
        kill_switch=_default_kill_switch,
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class RiskConfigResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    trading_enabled: bool
    live_trading_enabled: bool
    enabled_strategies: list[str]
    symbol_allowlist: list[str]
    max_order_quantity: str | None
    max_order_value: str | None
    max_total_exposure: str | None
    require_data_quality_passed: bool
    require_human_review: bool
    # R21.2 account-level rules (all tighten-only / fail-closed).
    max_symbol_exposure: str | None
    max_concentration_pct: str | None
    max_leverage: str | None
    max_price_deviation_pct: str | None
    max_signal_age_seconds: int | None
    require_market_open: bool
    duplicate_order_window_seconds: int | None
    duplicate_order_max_count: int
    # R21.3 stateful account rules.
    max_daily_loss_pct: str | None
    max_drawdown_floor_pct: str | None


class RiskDashboardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    kill_switch_active: bool
    kill_switch_reason: str | None
    config: RiskConfigResponse


class RiskContextResponse(BaseModel):
    """Read-only snapshot of the news/macro risk context."""

    model_config = ConfigDict(frozen=True)

    summary: dict[str, Any] = Field(
        description=(
            "JSON-safe view of the ResearchContextSummary; the "
            "untrusted-data invariant is included for audit."
        ),
    )
    decision: dict[str, Any] = Field(
        description=(
            "JSON-safe view of the RiskContextDecision; only "
            "tightens risk and never relaxes existing limits."
        ),
    )
    gate: RiskConfigResponse = Field(
        description="The currently active RiskGate configuration.",
    )
    kill_switch_active: bool
    query: dict[str, Any] = Field(
        description="Echo of the request parameters (for audit).",
    )


class RiskCheckRequest(BaseModel):
    """Request body for POST /api/v1/risk/check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: OrderIntent
    estimated_price: Decimal | None = None
    estimated_quantity: Decimal | None = None
    strategy_id: str | None = None
    data_quality_passed: bool = True
    risk_context: RiskContextDecision | None = None
    # Phase 19: live account state for the runtime total-exposure check.
    # When ``max_total_exposure`` is configured and this is omitted, the
    # gate fails closed (``account_context_required``). Supply it to
    # enforce the cap against the caller's projected exposure.
    account_context: AccountExposureContext | None = None


class RiskCheckResponse(BaseModel):
    """Response body for POST /api/v1/risk/check."""

    model_config = ConfigDict(frozen=True)

    decision_id: str
    approved: bool
    reason: str
    risk_tags: list[str]
    requires_human_review: bool
    max_quantity: str | None
    applied_risk_context: str | None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/config", response_model=RiskConfigResponse)
def get_risk_config() -> RiskConfigResponse:
    """Return the current RiskGate configuration."""
    gate = _get_risk_gate()
    limits = gate.limits
    return RiskConfigResponse(
        trading_enabled=limits.trading_enabled,
        live_trading_enabled=limits.live_trading_enabled,
        enabled_strategies=sorted(limits.enabled_strategies or ()),
        symbol_allowlist=sorted(limits.symbol_allowlist),
        max_order_quantity=(
            str(limits.max_order_quantity)
            if limits.max_order_quantity is not None
            else None
        ),
        max_order_value=(
            str(limits.max_order_value) if limits.max_order_value is not None else None
        ),
        max_total_exposure=(
            str(limits.max_total_exposure)
            if limits.max_total_exposure is not None
            else None
        ),
        require_data_quality_passed=limits.require_data_quality_passed,
        require_human_review=limits.require_human_review,
        max_symbol_exposure=(
            str(limits.max_symbol_exposure)
            if limits.max_symbol_exposure is not None
            else None
        ),
        max_concentration_pct=(
            str(limits.max_concentration_pct)
            if limits.max_concentration_pct is not None
            else None
        ),
        max_leverage=(
            str(limits.max_leverage) if limits.max_leverage is not None else None
        ),
        max_price_deviation_pct=(
            str(limits.max_price_deviation_pct)
            if limits.max_price_deviation_pct is not None
            else None
        ),
        max_signal_age_seconds=limits.max_signal_age_seconds,
        require_market_open=limits.require_market_open,
        duplicate_order_window_seconds=limits.duplicate_order_window_seconds,
        duplicate_order_max_count=limits.duplicate_order_max_count,
        max_daily_loss_pct=(
            str(limits.max_daily_loss_pct)
            if limits.max_daily_loss_pct is not None
            else None
        ),
        max_drawdown_floor_pct=(
            str(limits.max_drawdown_floor_pct)
            if limits.max_drawdown_floor_pct is not None
            else None
        ),
    )


@router.get("/dashboard", response_model=RiskDashboardResponse)
def get_risk_dashboard() -> RiskDashboardResponse:
    """Return the risk overview dashboard."""
    gate = _get_risk_gate()
    config = get_risk_config()
    return RiskDashboardResponse(
        kill_switch_active=gate.kill_switch.active,
        kill_switch_reason=gate.kill_switch.reason,
        config=config,
    )


def _parse_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip() != ""]


@router.get("/context", response_model=RiskContextResponse)
def get_risk_context(
    symbols: str | None = Query(
        default=None,
        description=(
            "Optional comma-separated list of symbols to filter news "
            "headlines. Empty/missing means all symbols."
        ),
    ),
    macro_indicators: str | None = Query(
        default=None,
        description=(
            "Optional comma-separated list of macro indicator IDs "
            "(e.g. ``fred:CPIAUCSL``)."
        ),
    ),
    start: datetime | None = Query(
        default=None,
        description="Optional ISO datetime lower bound for the window.",
    ),
    end: datetime | None = Query(
        default=None,
        description="Optional ISO datetime upper bound for the window.",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of news headlines to include.",
    ),
    decision_id: str = Query(
        default="rctx_api",
        min_length=1,
        description="Identifier echoed in the RiskContextDecision.",
    ),
) -> RiskContextResponse:
    """Read-only news/macro risk context.

    The endpoint composes a :class:`ResearchContextSummary` from the
    persistent news and macro stores, then derives the corresponding
    :class:`RiskContextDecision`. The response is **strictly
    read-only** — it never modifies the risk gate, never disables
    trading, and never relaxes existing limits.
    """
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=422,
            detail="start must be on or before end",
        )

    symbol_list = _parse_csv(symbols)
    macro_list = _parse_csv(macro_indicators)

    news_store = _get_news_store()
    macro_store = _get_macro_store()

    try:
        headlines = news_store.list_headlines(
            symbol=symbol_list[0] if symbol_list else None,
            start=start,
            end=end,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - report as 500
        raise HTTPException(
            status_code=500,
            detail=f"news store read failed: {exc}",
        ) from exc

    try:
        indicators = macro_store.list_indicators(
            indicator_id=macro_list[0] if macro_list else None,
            start=start,
            end=end,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - report as 500
        raise HTTPException(
            status_code=500,
            detail=f"macro store read failed: {exc}",
        ) from exc

    # Optional narrowing to the requested symbol/macro list so the
    # summary's reported counts match the user's query intent.
    if symbol_list:
        wanted = set(symbol_list)
        headlines = [h for h in headlines if any(sym in wanted for sym in h.symbols)]
    if macro_list:
        wanted_macro = set(macro_list)
        indicators = [i for i in indicators if i.indicator_id in wanted_macro]

    summary: ResearchContextSummary = build_structured_summary(
        headlines,
        indicators,
    )

    decision: RiskContextDecision = evaluate_news_macro_risk(
        summary,
        decision_id=decision_id,
    )

    config = get_risk_config()
    return RiskContextResponse(
        summary=summary.to_dict(),
        decision={
            "requires_human_review": decision.requires_human_review,
            "risk_tags": list(decision.risk_tags),
            "suggested_max_position_multiplier": (
                decision.suggested_max_position_multiplier
            ),
            "notes": list(decision.notes),
            "source_summary_untrusted": decision.source_summary_untrusted,
            "decision_id": decision.decision_id,
            "context_id": decision.context_id,
        },
        gate=config,
        kill_switch_active=_get_risk_gate().kill_switch.active,
        query={
            "symbols": symbol_list,
            "macro_indicators": macro_list,
            "start": start.isoformat() if start is not None else None,
            "end": end.isoformat() if end is not None else None,
            "limit": limit,
            "decision_id": decision_id,
        },
    )


@router.post("/check", response_model=RiskCheckResponse)
def post_risk_check(body: RiskCheckRequest) -> RiskCheckResponse:
    """Evaluate an OrderIntent through the live RiskGate.

    Optionally accepts a ``risk_context`` (a
    :class:`RiskContextDecision`) which is applied in a
    **tighten-only** manner. The response surfaces the merged
    decision's decision_id, approval, reason, tags, human-review
    flag, and (possibly reduced) ``max_quantity``.
    """
    gate = _get_risk_gate()
    decision = gate.evaluate(
        body.intent,
        strategy_id=body.strategy_id,
        estimated_price=body.estimated_price,
        estimated_quantity=body.estimated_quantity,
        data_quality_passed=body.data_quality_passed,
        risk_context=body.risk_context,
        account_context=body.account_context,
    )
    return RiskCheckResponse(
        decision_id=decision.decision_id,
        approved=decision.approved,
        reason=decision.reason,
        risk_tags=list(decision.risk_tags),
        requires_human_review=decision.requires_human_review,
        max_quantity=(
            str(decision.max_quantity) if decision.max_quantity is not None else None
        ),
        applied_risk_context=(
            body.risk_context.decision_id if body.risk_context is not None else None
        ),
    )


__all__ = [
    "RiskCheckRequest",
    "RiskCheckResponse",
    "RiskConfigResponse",
    "RiskContextResponse",
    "RiskDashboardResponse",
    "_get_macro_store",
    "_get_news_store",
    "_get_risk_gate",
    "_reset_risk_gate",
    "router",
]
