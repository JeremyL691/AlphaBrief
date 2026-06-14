"""Persistent storage layer for AlphaBrief API — DuckDB-backed.

This package provides a DuckDB-based data access layer that replaces
in-memory dictionaries for market data, backtest reports, briefs, paper
portfolio, audit logs, and review snapshots.
"""

from __future__ import annotations

from alphabrief_api.db.backtest_reports import BacktestReportStore
from alphabrief_api.db.market_data import MarketDataStore

__all__ = ["BacktestReportStore", "MarketDataStore"]
