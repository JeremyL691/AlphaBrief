"""DuckDB-backed store for shadow decisions and their scores (5.11).

The store owns its DDL locally (mirroring :mod:`alphabrief_trader.db_store`)
so the package can be imported and tested without pulling in the FastAPI
application graph. Decisions are append-only per
``(cycle_id, symbol, benchmark)``; a score is written once per horizon and
never overwrites committed evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_core import paths as _paths

from alphabrief_trader.shadow import (
    SHADOW_BENCHMARKS,
    SHADOW_HORIZONS_HOURS,
    ShadowDecision,
    ShadowScore,
    ShadowStats,
    summarize,
)

CREATE_SHADOW_TABLE = """
CREATE TABLE IF NOT EXISTS ai_shadow_decisions (
    cycle_id       TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    benchmark      TEXT NOT NULL,
    side           TEXT NOT NULL,
    source         TEXT NOT NULL,
    detail         TEXT NOT NULL,
    entry_mid      TEXT,
    decided_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (cycle_id, symbol, benchmark)
)
"""

CREATE_SHADOW_SCORES_TABLE = """
CREATE TABLE IF NOT EXISTS ai_shadow_scores (
    cycle_id       TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    benchmark      TEXT NOT NULL,
    horizon_hours  INTEGER NOT NULL,
    return_pct     TEXT NOT NULL,
    exit_mid       TEXT NOT NULL,
    spread_at_exit TEXT NOT NULL,
    scored_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (cycle_id, symbol, benchmark, horizon_hours)
)
"""

CREATE_SHADOW_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_shadow_decisions_decided
    ON ai_shadow_decisions (decided_at DESC, benchmark)
"""


class ShadowStore:
    """Persist shadow decisions and their 4h/24h scores."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _paths.db_path()
        self._conn = duckdb.connect(str(self._db_path))
        try:
            self._conn.execute(CREATE_SHADOW_TABLE)
            self._conn.execute(CREATE_SHADOW_SCORES_TABLE)
            self._conn.execute(CREATE_SHADOW_INDEX)
        except duckdb.TransactionException:
            pass

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def save_decisions(self, decisions: list[ShadowDecision]) -> int:
        """Persist decisions idempotently; returns the number of new rows."""
        inserted = 0
        for decision in decisions:
            if decision.benchmark not in SHADOW_BENCHMARKS:
                raise ValueError(
                    f"unknown shadow benchmark {decision.benchmark!r}"
                )
            existing = self._conn.execute(
                """
                SELECT 1 FROM ai_shadow_decisions
                WHERE cycle_id = ? AND symbol = ? AND benchmark = ?
                """,
                [decision.cycle_id, decision.symbol, decision.benchmark],
            ).fetchone()
            if existing is not None:
                continue
            self._conn.execute(
                """
                INSERT INTO ai_shadow_decisions (
                    cycle_id, symbol, benchmark, side, source, detail,
                    entry_mid, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    decision.cycle_id,
                    decision.symbol,
                    decision.benchmark,
                    decision.side,
                    decision.source,
                    decision.detail,
                    None if decision.entry_mid is None else str(decision.entry_mid),
                    decision.decided_at,
                ],
            )
            inserted += 1
        return inserted

    def list_decisions(
        self, *, cycle_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if cycle_id is None:
            rows = self._conn.execute(
                """
                SELECT cycle_id, symbol, benchmark, side, source, detail,
                       entry_mid, decided_at
                FROM ai_shadow_decisions
                ORDER BY decided_at DESC, cycle_id, symbol, benchmark
                LIMIT ?
                """,
                [limit],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT cycle_id, symbol, benchmark, side, source, detail,
                       entry_mid, decided_at
                FROM ai_shadow_decisions
                WHERE cycle_id = ?
                ORDER BY symbol, benchmark
                """,
                [cycle_id],
            ).fetchall()
        columns = (
            "cycle_id",
            "symbol",
            "benchmark",
            "side",
            "source",
            "detail",
            "entry_mid",
            "decided_at",
        )
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def due_for_scoring(
        self, *, now: datetime, horizons: tuple[int, ...] = SHADOW_HORIZONS_HOURS
    ) -> list[dict[str, Any]]:
        """Decisions whose horizon has passed but which have no score yet.

        Rows that are not decisions (a skipped or failed benchmark) are never
        due: scoring one as a flat decision would add a fake zero-return
        sample and make a missing benchmark look like a real ``no_trade``.
        """
        due: list[dict[str, Any]] = []
        for row in self.list_decisions(limit=10000):
            decided_at = row["decided_at"]
            if not isinstance(decided_at, datetime):
                continue
            for horizon in horizons:
                if now < decided_at + timedelta(hours=horizon):
                    continue
                scored = self._conn.execute(
                    """
                    SELECT 1 FROM ai_shadow_scores
                    WHERE cycle_id = ? AND symbol = ? AND benchmark = ?
                      AND horizon_hours = ?
                    """,
                    [row["cycle_id"], row["symbol"], row["benchmark"], horizon],
                ).fetchone()
                if scored is None:
                    due.append({**row, "horizon_hours": horizon})
        return due

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------

    def save_score(self, score: ShadowScore) -> bool:
        """Persist one score; returns False when it already existed."""
        if score.horizon_hours not in SHADOW_HORIZONS_HOURS:
            raise ValueError(f"unknown shadow horizon {score.horizon_hours}")
        existing = self._conn.execute(
            """
            SELECT 1 FROM ai_shadow_scores
            WHERE cycle_id = ? AND symbol = ? AND benchmark = ?
              AND horizon_hours = ?
            """,
            [
                score.cycle_id,
                score.symbol,
                score.benchmark,
                score.horizon_hours,
            ],
        ).fetchone()
        if existing is not None:
            return False
        self._conn.execute(
            """
            INSERT INTO ai_shadow_scores (
                cycle_id, symbol, benchmark, horizon_hours, return_pct,
                exit_mid, spread_at_exit, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                score.cycle_id,
                score.symbol,
                score.benchmark,
                score.horizon_hours,
                str(score.return_pct),
                str(score.exit_mid),
                str(score.spread_at_exit),
                score.scored_at,
            ],
        )
        return True

    def stats(self, *, horizon_hours: int) -> list[ShadowStats]:
        """Aggregate scored results per benchmark at one horizon."""
        rows = self._conn.execute(
            """
            SELECT benchmark, return_pct
            FROM ai_shadow_scores
            WHERE horizon_hours = ?
            ORDER BY benchmark, cycle_id, symbol
            """,
            [horizon_hours],
        ).fetchall()
        by_benchmark: dict[str, list[Decimal]] = {}
        for benchmark, return_pct in rows:
            by_benchmark.setdefault(str(benchmark), []).append(
                Decimal(str(return_pct))
            )
        return [
            summarize(
                by_benchmark.get(benchmark, []),
                benchmark=benchmark,
                horizon_hours=horizon_hours,
            )
            for benchmark in SHADOW_BENCHMARKS
        ]

    def scoreboard(self) -> dict[str, list[dict[str, str | int]]]:
        """The evaluation payload: every benchmark at every horizon."""
        board: dict[str, list[dict[str, str | int]]] = {}
        for horizon in SHADOW_HORIZONS_HOURS:
            stats = self.stats(horizon_hours=horizon)
            board[f"{horizon}h"] = [stat.to_dict() for stat in stats]
        return board

    def clear(self) -> None:
        """Drop the shadow tables (test isolation only)."""
        self._conn.execute("DROP TABLE IF EXISTS ai_shadow_scores")
        self._conn.execute("DROP TABLE IF EXISTS ai_shadow_decisions")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "CREATE_SHADOW_INDEX",
    "CREATE_SHADOW_SCORES_TABLE",
    "CREATE_SHADOW_TABLE",
    "ShadowStore",
    "utc_now",
]
