"""AI Trading Committee API routes.

Read-only and run-only surface for the paper-trading AI committee. The
``/run`` endpoint materializes a cycle from the supplied universe (or
the operator's saved watchlist when omitted), pushes each symbol
through the deterministic ``RiskGate`` and ``PaperBroker`` exactly
the way the scheduler task does, and persists the full
``DailyCycleRecord`` for replay.

Live trading is independently locked; ``ALPHABRIEF_LIVE_TRADING_ENABLED``
in the request body is ignored (it is read from the environment).
``ALPHABRIEF_AI_TRADING_ENABLED`` is also read from the environment —
the API is intentionally one-way with respect to feature flags.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    DisciplineConfig,
    MarketSnapshot,
    SnapshotLoader,
    TradingCommittee,
    is_ai_trading_enabled,
    is_live_trading_unlocked,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db import AiTradingStore

# ---------------------------------------------------------------------------
# Store + builder singletons (test-isolation via _reset_ai_state)
# ---------------------------------------------------------------------------

_store: AiTradingStore | None = None


def _get_store() -> AiTradingStore:
    global _store
    if _store is None:
        _store = AiTradingStore()
    return _store


def _reset_ai_state() -> None:
    """Clear the singleton store (test isolation)."""
    global _store
    if _store is not None:
        _store.close()
    _store = None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AiRunRequest(BaseModel):
    """Request body for POST /api/v1/ai/run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbols: list[str] = Field(min_length=1, max_length=50)
    reference_prices: dict[str, Decimal] | None = None
    time_horizon: str = Field(default="5 trading days", min_length=1)


class AiStatusResponse(BaseModel):
    """Response body for GET /api/v1/ai/status."""

    model_config = ConfigDict(frozen=True)

    ai_trading_enabled: bool
    live_trading_enabled: bool
    discipline: dict[str, Any]
    cycle_count: int


class AiCycleSummary(BaseModel):
    """Single cycle in the history list."""

    model_config = ConfigDict(frozen=True)

    cycle_id: str
    trading_day: str
    symbols: list[str]
    plan_count: int
    attempt_count: int
    executed_count: int
    blocked_count: int
    outcome: str
    enabled: bool
    live_trading_enabled: bool
    created_at: str


class AiHistoryResponse(BaseModel):
    """Response body for GET /api/v1/ai/history."""

    model_config = ConfigDict(frozen=True)

    cycles: list[AiCycleSummary]


class AiRulesResponse(BaseModel):
    """Response body for GET /api/v1/ai/rules."""

    model_config = ConfigDict(frozen=True)

    discipline: dict[str, Any]
    prompt_version: str
    roles: list[str]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/ai", tags=["ai-trading"])


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def _build_default_committee() -> TradingCommittee:
    """Build a deterministic committee backed by ``FakeProviderAdapter``."""
    sample_response = {
        "analysis": (
            "Trend remains constructive on improving breadth; downside risks "
            "centered on macro headlines and crowded positioning."
        ),
        "view": "bullish",
        "confidence": 0.62,
        "evidence": [
            "EMA20 above EMA50 with rising volume",
            "News tone modestly positive",
        ],
        "risks": ["Macro headline tail-risk", "Crowded long positioning"],
        "suggested_action": "watch",
        "target_position_pct": 0.10,
        "veto": False,
        "needs_human_review": True,
    }
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-ai-committee",
        capabilities=["structured_output"],
        structured_output=sample_response,
    )
    gateway = ModelGateway(providers=[provider])
    return TradingCommittee(
        gateway=gateway,
        discipline=DisciplineConfig(),
    )


def _build_paper_broker() -> PaperBroker:
    """Build an in-memory paper broker used by the API run path."""
    return PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )


def _build_risk_gate(symbols: list[str]) -> RiskGate:
    """Build a permissive risk gate scoped to ``symbols``."""
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset(symbols),
        )
    )


def _build_snapshot_loader(
    symbols: list[str],
    reference_prices: dict[str, Decimal] | None,
) -> SnapshotLoader:
    """Build a snapshot loader that returns a fake snapshot per symbol."""

    overrides = reference_prices or {}

    def _loader(symbol: str) -> MarketSnapshot | None:
        if symbol not in symbols:
            return None
        ref = overrides.get(symbol, Decimal("100"))
        return MarketSnapshot(
            symbol=symbol,
            reference_price=ref,
            recent_return_pct=Decimal("0"),
            recent_volume=Decimal("1000"),
            news_context=None,
            macro_context=None,
            data_version="api-runner-v1",
            captured_at=datetime.now(UTC),
        )

    return _loader


def _build_cycle(
    *,
    symbols: list[str],
    reference_prices: dict[str, Decimal] | None,
) -> DailyTradingCycle:
    """Build a fully wired daily cycle from the supplied universe."""
    return DailyTradingCycle(
        committee=_build_default_committee(),
        risk_gate=_build_risk_gate(symbols),
        broker=_build_paper_broker(),
        store=_get_store(),
        snapshot_loader=_build_snapshot_loader(symbols, reference_prices),
        enabled=is_ai_trading_enabled(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=AiStatusResponse)
def get_status() -> AiStatusResponse:
    """Return feature-flag state and aggregate cycle counts."""
    store = _get_store()
    cycles = store.list_cycles(limit=200)
    return AiStatusResponse(
        ai_trading_enabled=is_ai_trading_enabled(),
        live_trading_enabled=is_live_trading_unlocked(),
        discipline=DisciplineConfig().model_dump(mode="json"),
        cycle_count=len(cycles),
    )


@router.post("/run", status_code=201)
def run_cycle(body: AiRunRequest) -> dict[str, object]:
    """Run one daily cycle for the supplied universe."""
    if is_live_trading_unlocked():
        raise HTTPException(
            status_code=409,
            detail=(
                "ALPHABRIEF_LIVE_TRADING_ENABLED live-trading lock is set; "
                "AI trading is paper-only and refused to run"
            ),
        )

    if not is_ai_trading_enabled():
        raise HTTPException(
            status_code=409,
            detail=(
                "ALPHABRIEF_AI_TRADING_ENABLED is not set; "
                "refusing to execute — enable the feature flag first"
            ),
        )

    cycle = _build_cycle(
        symbols=list(body.symbols),
        reference_prices=(
            {k: Decimal(v) for k, v in body.reference_prices.items()}
            if body.reference_prices
            else None
        ),
    )
    record = cycle.run(
        list(body.symbols),
        time_horizon=body.time_horizon,
    )
    return {
        "cycle_id": record.cycle_id,
        "outcome": record.outcome,
        "summary": record.summary,
        "plan_count": len(record.plans),
        "attempt_count": len(record.attempts),
        "votes": [v.model_dump(mode="json") for v in record.votes],
        "plans": [p.model_dump(mode="json") for p in record.plans],
        "attempts": [a.model_dump(mode="json") for a in record.attempts],
    }


@router.get("/history", response_model=AiHistoryResponse)
def list_history(limit: int = 20) -> AiHistoryResponse:
    """List recent cycles, newest-first."""
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=422, detail="limit must be in [1, 200]"
        )
    store = _get_store()
    summaries = store.list_cycles(limit=limit)
    return AiHistoryResponse(
        cycles=[
            AiCycleSummary(
                cycle_id=s.cycle_id,
                trading_day=s.trading_day,
                symbols=list(s.symbols),
                plan_count=s.plan_count,
                attempt_count=s.attempt_count,
                executed_count=s.executed_count,
                blocked_count=s.blocked_count,
                outcome=s.outcome,
                enabled=s.enabled,
                live_trading_enabled=s.live_trading_enabled,
                created_at=s.created_at,
            )
            for s in summaries
        ]
    )


@router.get("/cycles/{cycle_id}")
def get_cycle(cycle_id: str) -> dict[str, Any]:
    """Return the full JSON record for a single cycle, or 404."""
    store = _get_store()
    record = store.get_cycle(cycle_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"cycle {cycle_id!r} not found"
        )
    return record


@router.get("/rules", response_model=AiRulesResponse)
def get_rules() -> AiRulesResponse:
    """Return the active discipline rules + prompt version + role list."""
    config = DisciplineConfig()
    return AiRulesResponse(
        discipline=config.model_dump(mode="json"),
        prompt_version="aitrader-v1",
        roles=["technical", "fundamental", "risk", "manager"],
    )


@router.get("/attempts")
def list_attempts(limit: int = 50) -> dict[str, Any]:
    """Return recent order attempts, newest-first."""
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=422, detail="limit must be in [1, 200]"
        )
    store = _get_store()
    rows = store.list_attempts(limit=limit)
    return {"attempts": rows}


__all__ = [
    "AiCycleSummary",
    "AiHistoryResponse",
    "AiRulesResponse",
    "AiRunRequest",
    "AiStatusResponse",
    "_reset_ai_state",
    "router",
]
