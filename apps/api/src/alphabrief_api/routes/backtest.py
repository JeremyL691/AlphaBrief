"""Backtest routes for the AlphaBrief API — run backtests and retrieve reports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from alphabrief_backtest import BacktestReport, VectorizedBacktester
from alphabrief_core import Bar
from alphabrief_data import FeatureGenerationError, generate_basic_features
from alphabrief_gym import (
    AlphaBriefTradingEnvConfig,
    AlphaBriefTradingEnvV2,
    EnvV2Report,
    build_env_v2_report,
    env_v2_report_to_dict,
)
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

from alphabrief_api.db import BacktestReportStore
from alphabrief_api.routes.data import _get_store, _get_stored_bars

# ---------------------------------------------------------------------------
# Persistent report store (DuckDB-backed)
# ---------------------------------------------------------------------------

_report_store: BacktestReportStore | None = None
"""Module-level singleton for the DuckDB-backed backtest report store."""


def _get_report_store() -> BacktestReportStore:
    """Return the singleton BacktestReportStore, creating it on first access."""
    global _report_store
    if _report_store is None:
        _report_store = BacktestReportStore()
    return _report_store


def _clear_report_store() -> None:
    """Clear the persistent report store (for test isolation)."""
    global _report_store
    if _report_store is not None:
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
    engine: Literal["legacy", "env_v2"] = "legacy"
    symbols: list[str] = Field(default_factory=list)
    env_v2_max_leverage: Decimal = Field(default=Decimal("1"))
    env_v2_allow_short: bool = False
    env_v2_fee_bps: Decimal = Field(default=Decimal("5"))
    env_v2_slippage_bps: Decimal = Field(default=Decimal("5"))


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
    # R21.4 credibility metrics. ``None`` fields stay ``None`` for
    # degenerate runs (single bar, zero variance, no trades).
    benchmark_total_return: float | None = None
    alpha_vs_benchmark: float | None = None
    cagr: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    turnover: float
    exposure_pct: float


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
    engine: str = "legacy"


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


class EnvV2CostBreakdownResponse(BaseModel):
    """Cost breakdown for an EnvV2 backtest report response."""

    model_config = ConfigDict(frozen=True)

    slippage_cost: float
    market_impact_cost: float
    borrow_cost: float
    total_cost: float


class EnvV2AssetMetricsResponse(BaseModel):
    """Per-asset metrics for an EnvV2 backtest report response."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    final_position: float
    realized_pnl: float
    trade_count: int


class EnvV2BacktestReportResponse(BaseModel):
    """Response body for the EnvV2 engine branch of POST /api/v1/backtest/run."""

    model_config = ConfigDict(frozen=True)

    report_id: str
    environment: str
    steps: int
    initial_value: float
    final_value: float
    total_return: float
    max_drawdown: float
    trade_count: int
    final_leverage: float
    costs: EnvV2CostBreakdownResponse
    assets: list[EnvV2AssetMetricsResponse]
    generated_at: str


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
    m = report.metrics
    return BacktestMetricsResponse(
        total_return=float(m.total_return),
        max_drawdown=float(m.max_drawdown),
        trade_count=m.trade_count,
        win_rate=float(m.win_rate) if m.win_rate is not None else None,
        benchmark_total_return=(
            float(m.benchmark_total_return)
            if m.benchmark_total_return is not None
            else None
        ),
        alpha_vs_benchmark=(
            float(m.alpha_vs_benchmark) if m.alpha_vs_benchmark is not None else None
        ),
        cagr=float(m.cagr) if m.cagr is not None else None,
        sharpe=float(m.sharpe) if m.sharpe is not None else None,
        sortino=float(m.sortino) if m.sortino is not None else None,
        turnover=float(m.turnover),
        exposure_pct=float(m.exposure_pct),
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


def _list_all_bar_lists(bars_by_symbol: dict[str, list[Bar]]) -> list[Bar]:
    flat: list[Bar] = []
    for symbol in sorted(bars_by_symbol.keys()):
        flat.extend(bars_by_symbol[symbol])
    return flat


def _build_env_v2_config(req: BacktestRunRequest) -> AlphaBriefTradingEnvConfig:
    return AlphaBriefTradingEnvConfig(
        initial_cash=req.initial_cash,
        max_leverage=req.env_v2_max_leverage,
        allow_short=req.env_v2_allow_short,
        fee_bps=req.env_v2_fee_bps,
        slippage_bps=req.env_v2_slippage_bps,
    )


def _run_equal_weight_buy_and_hold(env: AlphaBriefTradingEnvV2) -> None:
    """Run a deterministic equal-weight buy-and-hold episode.

    At step 0 the portfolio is rebalanced to equal weights across all
    assets. On subsequent steps the current portfolio weights are
    passed through as targets so that no further trades occur.
    """
    assets = env.assets
    n_assets = len(assets)
    if n_assets == 0:
        return
    equal_weight = Decimal("1") / Decimal(n_assets)
    action = {asset: equal_weight for asset in assets}
    result = env.step(action)
    while not result.terminated:
        portfolio_value = result.observation.portfolio.portfolio_value
        if portfolio_value == 0:
            hold_action = {asset: Decimal("0") for asset in assets}
        else:
            hold_action = {}
            for asset in assets:
                observation = result.observation.assets[asset]
                position_value = observation.position_quantity * observation.close
                hold_action[asset] = position_value / portfolio_value
        result = env.step(hold_action)


def _env_v2_report_to_response(
    report_id: str,
    report: EnvV2Report,
) -> EnvV2BacktestReportResponse:
    return EnvV2BacktestReportResponse(
        report_id=report_id,
        environment=report.environment,
        steps=report.steps,
        initial_value=float(report.initial_value),
        final_value=float(report.final_value),
        total_return=float(report.total_return),
        max_drawdown=float(report.max_drawdown),
        trade_count=report.trade_count,
        final_leverage=float(report.final_leverage),
        costs=EnvV2CostBreakdownResponse(
            slippage_cost=float(report.costs.slippage_cost),
            market_impact_cost=float(report.costs.market_impact_cost),
            borrow_cost=float(report.costs.borrow_cost),
            total_cost=float(report.costs.total_cost),
        ),
        assets=[
            EnvV2AssetMetricsResponse(
                symbol=asset.symbol,
                final_position=float(asset.final_position),
                realized_pnl=float(asset.realized_pnl),
                trade_count=asset.trade_count,
            )
            for asset in report.assets
        ],
        generated_at=report.generated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=BacktestReportResponse | EnvV2BacktestReportResponse,
    status_code=201,
)
def run_backtest(
    body: BacktestRunRequest,
) -> BacktestReportResponse | EnvV2BacktestReportResponse:
    """Run a backtest and return the report.

    The *engine* field selects the backtest implementation. The default
    ``legacy`` engine runs the single-asset vectorized backtester. The
    ``env_v2`` engine runs the multi-asset ``AlphaBriefTradingEnvV2``
    with a deterministic equal-weight buy-and-hold policy.
    """
    if body.engine == "legacy":
        return _run_legacy_backtest(body)
    return _run_env_v2_backtest(body)


def _run_legacy_backtest(body: BacktestRunRequest) -> BacktestReportResponse:
    """Run the legacy single-asset vectorized backtester."""
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

    report_dict = report.model_dump(mode="json")
    store = _get_report_store()
    report_id = store.save_report(
        report_dict, symbol=body.symbol, strategy_name=body.strategy_name
    )

    return _report_to_response(report_id, report)


def _run_env_v2_backtest(
    body: BacktestRunRequest,
) -> EnvV2BacktestReportResponse:
    """Run the multi-asset EnvV2 backtest engine."""
    symbols = body.symbols or body.symbol_universe or [body.symbol]
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise HTTPException(status_code=422, detail="no symbols provided")
    if any(not s for s in symbols):
        raise HTTPException(
            status_code=422, detail="symbol list contains empty symbols"
        )

    store = _get_store()
    bars_by_symbol = store.get_bar_models_for_symbols(symbols)

    missing = [s for s in symbols if len(bars_by_symbol.get(s, [])) == 0]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"missing or empty bars for symbols: {sorted(missing)}",
        )

    insufficient = [s for s in symbols if len(bars_by_symbol.get(s, [])) < 2]
    if insufficient:
        raise HTTPException(
            status_code=422,
            detail=f"insufficient bars (need >= 2) for symbols: {sorted(insufficient)}",
        )

    bar_counts = {s: len(bars_by_symbol[s]) for s in symbols}
    if len(set(bar_counts.values())) != 1:
        raise HTTPException(
            status_code=422,
            detail=f"mismatched bar counts across symbols: {bar_counts}",
        )

    config = _build_env_v2_config(body)
    flat_bars = _list_all_bar_lists(bars_by_symbol)
    env = AlphaBriefTradingEnvV2(flat_bars, config=config)
    _run_equal_weight_buy_and_hold(env)

    report = build_env_v2_report(env)
    report_dict = env_v2_report_to_dict(report)
    joined_symbols = ",".join(symbols)
    report_store = _get_report_store()
    report_id = report_store.save_env_v2_report(
        report_dict, symbol=joined_symbols, strategy_name=body.strategy_name
    )

    response = _env_v2_report_to_response(report_id, report)
    return response


@router.get("/reports", response_model=BacktestReportsList)
def list_reports() -> BacktestReportsList:
    """List all historical backtest reports."""
    store = _get_report_store()
    rows = store.list_reports()
    summaries: list[BacktestReportSummary] = []
    for row in rows:
        engine = row.get("report_engine", "legacy")
        if engine == "env_v2":
            report = row["report"]
            try:
                summaries.append(
                    BacktestReportSummary(
                        report_id=str(row["id"]),
                        strategy_id=str(report.get("environment", "env_v2")),
                        strategy_version="0.0.0",
                        symbol=str(row["symbol"]),
                        data_version="env_v2",
                        final_value=float(report["final_value"]),
                        trade_count=int(report["trade_count"]),
                        total_return=float(report["total_return"]),
                        engine="env_v2",
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        else:
            try:
                report = BacktestReport.model_validate(row["report"])
            except Exception:
                continue
            summaries.append(_report_to_summary(str(row["id"]), report))
    return BacktestReportsList(reports=summaries)


@router.get("/report/{report_id}", response_model=BacktestReportResponse)
def get_report(report_id: str) -> BacktestReportResponse:
    """Retrieve a single complete backtest report by ID."""
    store = _get_report_store()
    row = store.get_report(report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"report {report_id!r} not found")
    try:
        report = BacktestReport.model_validate(row["report"])
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"invalid persisted report: {exc}"
        ) from exc
    return _report_to_response(report_id, report)


__all__ = [
    "BacktestReportResponse",
    "BacktestReportSummary",
    "BacktestReportsList",
    "BacktestRunRequest",
    "EnvV2AssetMetricsResponse",
    "EnvV2BacktestReportResponse",
    "EnvV2CostBreakdownResponse",
    "_clear_report_store",
    "router",
]
