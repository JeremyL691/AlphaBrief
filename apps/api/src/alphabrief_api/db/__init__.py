"""Persistent storage layer for AlphaBrief API — DuckDB-backed.

This package provides a DuckDB-based data access layer that replaces
in-memory dictionaries for market data, backtest reports, briefs, paper
portfolio, audit logs, review snapshots, debate records, news headlines,
macro-economic indicators, model evaluations, strategy specs,
strategy signal history, and AI Trading Committee cycles.
"""

from __future__ import annotations

from alphabrief_api.db.ai_trading import AiTradingStore
from alphabrief_api.db.backtest_reports import BacktestReportStore
from alphabrief_api.db.briefs import BriefStore
from alphabrief_api.db.debates import DebateStore
from alphabrief_api.db.macro import MacroStore
from alphabrief_api.db.market_data import MarketDataStore
from alphabrief_api.db.model_eval import ModelEvalStore
from alphabrief_api.db.news import NewsStore
from alphabrief_api.db.paper import PaperStore
from alphabrief_api.db.review import ReviewStore
from alphabrief_api.db.strategies import StrategySpecStore
from alphabrief_api.db.strategy_signals import StrategySignalStore

__all__ = [
    "AiTradingStore",
    "BacktestReportStore",
    "BriefStore",
    "DebateStore",
    "MacroStore",
    "MarketDataStore",
    "ModelEvalStore",
    "NewsStore",
    "PaperStore",
    "ReviewStore",
    "StrategySignalStore",
    "StrategySpecStore",
]
