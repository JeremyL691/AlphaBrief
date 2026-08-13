"""Backtesting utilities for AlphaBrief."""

from alphabrief_backtest.execution import (
    DEFAULT_MAX_PRICE_AGE_SECONDS,
    OrderFill,
    OrderRequest,
    execute_order,
    financing_charge,
)
from alphabrief_backtest.metadata import (
    CATEGORY_SESSION_WINDOWS,
    SEMANTICS_DIFFERENCES,
    SEMANTICS_VERSION,
    BacktestConstraintError,
    BacktestInstrumentMetadata,
    BacktestMetadataSet,
    BacktestSessionWindow,
    default_session_window,
    normalize_backtest_price,
    normalize_backtest_units,
)
from alphabrief_backtest.portfolio import (
    CategoryAttribution,
    FinancingEvent,
    PortfolioSimulator,
    PortfolioSnapshot,
    PositionState,
)
from alphabrief_backtest.vectorized import (
    BacktestMetrics,
    BacktestReport,
    BacktestTrade,
    EquityPoint,
    VectorizedBacktester,
    write_backtest_report,
)
from alphabrief_backtest.walk_forward import (
    WalkForwardError,
    WalkForwardResult,
    WalkForwardWindow,
    run_walk_forward,
)

__all__ = [
    "CATEGORY_SESSION_WINDOWS",
    "DEFAULT_MAX_PRICE_AGE_SECONDS",
    "SEMANTICS_DIFFERENCES",
    "SEMANTICS_VERSION",
    "BacktestConstraintError",
    "BacktestInstrumentMetadata",
    "BacktestMetadataSet",
    "BacktestMetrics",
    "BacktestReport",
    "BacktestSessionWindow",
    "BacktestTrade",
    "CategoryAttribution",
    "EquityPoint",
    "FinancingEvent",
    "OrderFill",
    "OrderRequest",
    "PortfolioSimulator",
    "PortfolioSnapshot",
    "PositionState",
    "VectorizedBacktester",
    "WalkForwardError",
    "WalkForwardResult",
    "WalkForwardWindow",
    "default_session_window",
    "execute_order",
    "financing_charge",
    "normalize_backtest_price",
    "normalize_backtest_units",
    "run_walk_forward",
    "write_backtest_report",
]
