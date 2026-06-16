"""Persistent storage layer for AlphaBrief API — DuckDB-backed.

This package provides a DuckDB-based data access layer that replaces
in-memory dictionaries for market data, backtest reports, briefs, paper
portfolio, audit logs, review snapshots, debate records, news headlines,
and macro-economic indicators.
"""

from __future__ import annotations

from alphabrief_api.db.backtest_reports import BacktestReportStore
from alphabrief_api.db.briefs import BriefStore
from alphabrief_api.db.debates import DebateStore
from alphabrief_api.db.macro import MacroStore
from alphabrief_api.db.market_data import MarketDataStore
from alphabrief_api.db.news import NewsStore
from alphabrief_api.db.paper import PaperStore
from alphabrief_api.db.review import ReviewStore

__all__ = [
    "BacktestReportStore",
    "BriefStore",
    "DebateStore",
    "MacroStore",
    "MarketDataStore",
    "NewsStore",
    "PaperStore",
    "ReviewStore",
]
