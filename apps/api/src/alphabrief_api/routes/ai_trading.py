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

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_models import ModelCallBudget, ModelCallRecord
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyCycleRecord,
    DailyTradingCycle,
    DisciplineConfig,
    MarketSnapshot,
    ModelProviderUnavailableError,
    SnapshotLoader,
    StoredMarketSnapshotBuilder,
    TradingCommittee,
    build_ai_trading_committee,
    is_ai_trading_enabled,
    is_live_trading_unlocked,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db import AiTradingStore, MarketDataStore, NewsStore
from alphabrief_api.db.model_call import ModelCallStore

# ---------------------------------------------------------------------------
# Store + builder singletons (test-isolation via _reset_ai_state)
# ---------------------------------------------------------------------------

_store: AiTradingStore | None = None
_call_store: ModelCallStore | None = None


def _get_store() -> AiTradingStore:
    global _store
    if _store is None:
        _store = AiTradingStore()
    return _store


def _get_call_store() -> ModelCallStore:
    """Return the singleton durable model-call record store."""
    global _call_store
    if _call_store is None:
        _call_store = ModelCallStore()
    return _call_store


def _reset_ai_state() -> None:
    """Clear the singleton store (test isolation)."""
    global _store, _call_store
    if _store is not None:
        _store.close()
    _store = None
    if _call_store is not None:
        _call_store.close()
    _call_store = None


# ---------------------------------------------------------------------------
# Observation-dir reader (scheduler export fallback)
# ---------------------------------------------------------------------------
#
# The scheduler holds the DuckDB write lock on its own database for its
# lifetime, so the API cannot query it directly (DuckDB is single-writer).
# The scheduler exports one ``ai_cycle_<trading_day>.json`` per cycle;
# when ``ALPHABRIEF_AI_OBSERVATION_DIR`` is set, the read-only AI
# endpoints serve those exports instead of the API's own (separate) DB.


def _observation_dir() -> Path | None:
    raw = os.environ.get("ALPHABRIEF_AI_OBSERVATION_DIR", "").strip()
    return Path(raw) if raw else None


def _observation_records() -> list[dict[str, Any]]:
    obs_dir = _observation_dir()
    if obs_dir is None or not obs_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(obs_dir.glob("ai_cycle_*.json")):
        if path.name.startswith("ai_cycle_error_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("cycle_id"):
            records.append(data)
    records.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return records


def _cycle_summary_from_record(record: dict[str, Any]) -> AiCycleSummary:
    attempts = record.get("attempts") or []
    plans = record.get("plans") or []
    return AiCycleSummary(
        cycle_id=str(record["cycle_id"]),
        trading_day=str(record.get("trading_day") or ""),
        symbols=[str(s) for s in (record.get("symbols") or [])],
        plan_count=len(plans),
        attempt_count=len(attempts),
        executed_count=sum(
            1 for a in attempts if a.get("outcome") == "executed"
        ),
        blocked_count=sum(
            1
            for a in attempts
            if str(a.get("outcome") or "").startswith("blocked")
        ),
        outcome=str(record.get("outcome") or ""),
        enabled=bool(record.get("enabled")),
        live_trading_enabled=bool(record.get("live_trading_enabled")),
        created_at=str(record.get("created_at") or ""),
    )


def _list_summaries(limit: int) -> list[AiCycleSummary]:
    """Return recent cycle summaries from the best available source."""
    if _observation_dir() is not None:
        return [
            _cycle_summary_from_record(record)
            for record in _observation_records()[:limit]
        ]
    store = _get_store()
    summaries = store.list_cycles(limit=limit)
    return [
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
    """Build the configured AI Trading Committee.

    Every terminal ModelGateway call is persisted to the durable
    ``ModelCallStore`` and bounded by a per-request/cycle/day budget, so
    the trading path keeps complete, replayable model evidence.
    """
    return build_ai_trading_committee(
        record_sink=_persist_call_record,
        budget=ModelCallBudget(),
    )


def _persist_call_record(record: ModelCallRecord) -> None:
    """Persist one terminal gateway call record (sink callback)."""
    _get_call_store().save_call(record)


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
) -> tuple[SnapshotLoader, Callable[[], None]]:
    """Build a store-backed snapshot loader plus a close callback."""

    symbol_set = {symbol.strip().upper() for symbol in symbols}
    overrides = reference_prices or {}
    market_store = MarketDataStore()
    news_store = NewsStore()
    builder = StoredMarketSnapshotBuilder(
        bar_loader=market_store.get_bar_models,
        headline_loader=lambda symbol, start, end, limit: (
            news_store.list_headlines(
                symbol=symbol,
                start=start,
                end=end,
                limit=limit,
            )
        ),
    )

    def _loader(symbol: str) -> MarketSnapshot | None:
        normalized = symbol.strip().upper()
        if normalized not in symbol_set:
            return None
        return builder.build(
            normalized,
            reference_price_override=overrides.get(normalized),
        )

    def _close() -> None:
        news_store.close()
        market_store.close()

    return _loader, _close


def _build_cycle(
    *,
    snapshot_loader: SnapshotLoader,
    symbols: list[str],
) -> DailyTradingCycle:
    """Build a fully wired daily cycle from the supplied universe."""
    return DailyTradingCycle(
        committee=_build_default_committee(),
        risk_gate=_build_risk_gate(symbols),
        broker=_build_paper_broker(),
        store=_get_store(),
        snapshot_loader=snapshot_loader,
        enabled=is_ai_trading_enabled(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=AiStatusResponse)
def get_status() -> AiStatusResponse:
    """Return feature-flag state and aggregate cycle counts."""
    summaries = _list_summaries(limit=200)
    return AiStatusResponse(
        ai_trading_enabled=is_ai_trading_enabled(),
        live_trading_enabled=is_live_trading_unlocked(),
        discipline=DisciplineConfig().model_dump(mode="json"),
        cycle_count=len(summaries),
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

    symbols = [symbol.strip().upper() for symbol in body.symbols]
    reference_prices = (
        {k.strip().upper(): Decimal(v) for k, v in body.reference_prices.items()}
        if body.reference_prices
        else None
    )
    snapshot_loader, close_snapshot_loader = _build_snapshot_loader(
        symbols=symbols,
        reference_prices=reference_prices,
    )
    try:
        try:
            cycle = _build_cycle(
                snapshot_loader=snapshot_loader,
                symbols=symbols,
            )
        except ModelProviderUnavailableError as exc:
            record = _blocked_record_without_provider(
                symbols=symbols, reason=str(exc)
            )
            return _cycle_payload(record)
        record = cycle.run(
            symbols,
            time_horizon=body.time_horizon,
            cycle_key=_api_cycle_key(symbols),
        )
    finally:
        close_snapshot_loader()
    return _cycle_payload(record)


def _api_cycle_key(symbols: list[str]) -> str:
    """Deterministic API cycle key: one terminal result per day+universe.

    Repeating the same day and symbols returns the existing terminal
    cycle record instead of running the committee again (REQ-AI-009);
    a different snapshot fingerprint still produces a new run.
    """
    return f"api:{datetime.now(UTC).date().isoformat()}:{','.join(sorted(symbols))}"


def _blocked_record_without_provider(
    symbols: list[str], *, reason: str
) -> DailyCycleRecord:
    """Persist a durable fail-closed cycle when no model provider exists.

    The cycle cannot produce research without a configured provider, so
    no proposal, OrderIntent, or broker submission may exist. The record
    keeps the trading-day ledger honest: outcome is a no-trade value and
    the summary states the real cause. It carries the deterministic
    cycle key so repeated failures collapse into one durable record.
    """
    record = DailyCycleRecord(
        cycle_id=f"aic_{os.urandom(6).hex()}",
        trading_day=datetime.now(UTC).date().isoformat(),
        symbols=list(symbols),
        plans=[],
        votes=[],
        attempts=[],
        outcome="skipped_no_intent",
        enabled=True,
        live_trading_enabled=False,
        summary=(
            "model provider unavailable; cycle produced no research or "
            f"order intent (fail closed): {reason}"
        ),
        cycle_key=_api_cycle_key(symbols),
        created_at=datetime.now(UTC),
    )
    _get_store().save_cycle(record)
    return record


def _cycle_payload(record: DailyCycleRecord) -> dict[str, object]:
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
    return AiHistoryResponse(cycles=_list_summaries(limit=limit))


@router.get("/cycles/{cycle_id}")
def get_cycle(cycle_id: str) -> dict[str, Any]:
    """Return the full JSON record for a single cycle, or 404."""
    if _observation_dir() is not None:
        for record in _observation_records():
            if record.get("cycle_id") == cycle_id:
                return record
        raise HTTPException(
            status_code=404, detail=f"cycle {cycle_id!r} not found"
        )
    store = _get_store()
    stored = store.get_cycle(cycle_id)
    if stored is None:
        raise HTTPException(
            status_code=404, detail=f"cycle {cycle_id!r} not found"
        )
    return stored


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
    if _observation_dir() is not None:
        attempts: list[dict[str, Any]] = []
        for record in _observation_records():
            cycle_id = record.get("cycle_id")
            for attempt in record.get("attempts") or []:
                attempts.append(
                    {
                        "intent_id": str(attempt.get("intent_id") or ""),
                        "cycle_id": str(cycle_id or ""),
                        "outcome": str(attempt.get("outcome") or ""),
                        "approved": bool(attempt.get("approved")),
                        "requires_human_review": bool(
                            attempt.get("requires_human_review")
                        ),
                        "filled": bool(attempt.get("filled")),
                        "order_id": attempt.get("order_id"),
                        "created_at": str(attempt.get("created_at") or ""),
                        "attempt": attempt,
                    }
                )
                if len(attempts) >= limit:
                    break
            if len(attempts) >= limit:
                break
        return {"attempts": attempts}
    store = _get_store()
    rows = store.list_attempts(limit=limit)
    return {"attempts": rows}


__all__ = [
    "AiCycleSummary",
    "AiHistoryResponse",
    "AiRulesResponse",
    "AiRunRequest",
    "AiStatusResponse",
    "_blocked_record_without_provider",
    "_cycle_payload",
    "_persist_call_record",
    "_reset_ai_state",
    "router",
]
