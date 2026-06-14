"""Backtest routes for the AlphaBrief API — run backtests and retrieve reports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from alphabrief_backtest import BacktestReport, VectorizedBacktester
from alphabrief_data import FeatureGenerationError, generate_basic_features
from alphabrief_strategy import (
    EvaluationPeriod,
    MovingAverageTrendStrategy,
    StrategyCosts,
    StrategyEvaluation,
    StrategyRisk,
    StrategyRule,
    StrategySpec,
    StrategyUniverse,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.routes.data import _get_stored_bars

# ---------------------------------------------------------------------------
# In-memory report store
# ---------------------------------------------------------------------------

_report_store: dict[str, BacktestReport] = {}


def _clear_reports() -> None:
    """Clear the in-memory report store (for test isolation)."""
    _report_store.clear()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class BacktestRunRequest(BaseModel):
    """Request body for POST /api/v1/backtest/run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1)
    strategy_id: str = "ma_trend"
    strategy_name: str = "Moving Average Trend"
    strategy_version: str = "0.0.0"
    symbol_universe: list[str] = Field(default_factory=list)
    entry_condition: str = "close > close_sma_3"
    exit_condition: str = "close <= close_sma_3"
    max_position_pct: Decimal = Field(default=Decimal("1.0"))
    fee_bps: Decimal = Field(default=Decimal("5"))
    slippage_bps: Decimal = Field(default=Decimal("5"))
    sma_window: int = Field(default=3, ge=1)
    initial_cash: Decimal = Field(default=Decimal("10000"))
    train_start: date = Field(default_factory=lambda: date(2020, 1, 1))
    train_end: date = Field(default_factory=lambda: date(2023, 12, 31))
    test_start: date = Field(default_factory=lambda: date(2024, 1, 1))
    test_end: date = Field(default_factory=lambda: date(2026, 12, 31))


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class BacktestMetricsResponse(BaseModel):
    """Metrics extracted from a BacktestReport."""

    model_config = ConfigDict(frozen=True)

    total_return: float
    max_drawdown: float
    trade_count: int
    win_rate: float | None


class BacktestReportSummary(BaseModel):
    """Brief summary of a backtest report (for list endpoint)."""

    model_config = ConfigDict(frozen=True)

    report_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    data_version: str
    final_value: float
    trade_count: int
    total_return: float


class BacktestReportResponse(BaseModel):
    """Full backtest report response."""

    model_config = ConfigDict(frozen=True)

    report_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    data_version: str
    initial_cash: float
    final_value: float
    fee_bps: float
    slippage_bps: float
    metrics: BacktestMetricsResponse
    trades: list[dict[str, object]]
    equity_curve: list[dict[str, object]]


class BacktestReportsList(BaseModel):
    """Response body for GET /api/v1/backtest/reports."""

    model_config = ConfigDict(frozen=True)

    reports: list[BacktestReportSummary]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_strategy_spec(req: BacktestRunRequest) -> StrategySpec:
    """Build a StrategySpec from the API request parameters."""
    symbol_universe = req.symbol_universe or [req.symbol]
    return StrategySpec(
        strategy_id=req.strategy_id,
        name=req.strategy_name,
        version=req.strategy_version,
        universe=StrategyUniverse(symbols=symbol_universe),
        timeframe="1min",
        entry=StrategyRule(condition=req.entry_condition),
        exit=StrategyRule(condition=req.exit_condition),
        risk=StrategyRisk(max_position_pct=req.max_position_pct),
        costs=StrategyCosts(fee_bps=req.fee_bps, slippage_bps=req.slippage_bps),
        evaluation=StrategyEvaluation(
            train_period=EvaluationPeriod(start=req.train_start, end=req.train_end),
            test_period=EvaluationPeriod(start=req.test_start, end=req.test_end),
        ),
    )


def _report_metrics_to_response(report: BacktestReport) -> BacktestMetricsResponse:
    return BacktestMetricsResponse(
        total_return=float(report.metrics.total_return),
        max_drawdown=float(report.metrics.max_drawdown),
        trade_count=report.metrics.trade_count,
        win_rate=(
            float(report.metrics.win_rate)
            if report.metrics.win_rate is not None
            else None
        ),
    )


def _report_to_summary(report_id: str, report: BacktestReport) -> BacktestReportSummary:
    return BacktestReportSummary(
        report_id=report_id,
        strategy_id=report.strategy_id,
        strategy_version=report.strategy_version,
        symbol=report.symbol,
        data_version=report.data_version,
        final_value=float(report.final_value),
        trade_count=report.metrics.trade_count,
        total_return=float(report.metrics.total_return),
    )


def _report_to_response(
    report_id: str,
    report: BacktestReport,
) -> BacktestReportResponse:
    return BacktestReportResponse(
        report_id=report_id,
        strategy_id=report.strategy_id,
        strategy_version=report.strategy_version,
        symbol=report.symbol,
        data_version=report.data_version,
        initial_cash=float(report.initial_cash),
        final_value=float(report.final_value),
        fee_bps=float(report.fee_bps),
        slippage_bps=float(report.slippage_bps),
        metrics=_report_metrics_to_response(report),
        trades=[t.model_dump(mode="json") for t in report.trades],
        equity_curve=[e.model_dump(mode="json") for e in report.equity_curve],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/run", response_model=BacktestReportResponse, status_code=201)
def run_backtest(body: BacktestRunRequest) -> BacktestReportResponse:
    """Run a vectorized backtest and return the report.

    Requires *symbol* to be loaded via POST /api/v1/data/load first.
    """
    bars = _get_stored_bars(body.symbol)
    if len(bars) < body.sma_window:
        raise HTTPException(
            status_code=422,
            detail=f"insufficient bars: need at least {body.sma_window}, "
            f"got {len(bars)}",
        )

    try:
        features = generate_basic_features(
            bars,
            return_periods=(1,),
            sma_windows=(body.sma_window,),
        )
    except FeatureGenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    spec = _build_strategy_spec(body)
    strategy = MovingAverageTrendStrategy(sma_window=body.sma_window)

    backtester = VectorizedBacktester(initial_cash=body.initial_cash)
    report = backtester.run(strategy=strategy, spec=spec, bars=bars, features=features)

    report_id = f"backtest_{uuid4().hex[:12]}"
    _report_store[report_id] = report

    return _report_to_response(report_id, report)


@router.get("/reports", response_model=BacktestReportsList)
def list_reports() -> BacktestReportsList:
    """List all historical backtest reports."""
    summaries = [
        _report_to_summary(rid, report)
        for rid, report in _report_store.items()
    ]
    return BacktestReportsList(reports=summaries)


@router.get("/report/{report_id}", response_model=BacktestReportResponse)
def get_report(report_id: str) -> BacktestReportResponse:
    """Retrieve a single complete backtest report by ID."""
    report = _report_store.get(report_id)
    if report is None:
        raise HTTPException(
            status_code=404, detail=f"report {report_id!r} not found"
        )
    return _report_to_response(report_id, report)


__all__ = [
    "BacktestReportResponse",
    "BacktestReportSummary",
    "BacktestReportsList",
    "BacktestRunRequest",
    "router",
]
