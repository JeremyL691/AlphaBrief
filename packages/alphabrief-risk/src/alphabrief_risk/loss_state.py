"""Durable day, high-water, and loss-streak state (M08-W04).

DuckDB-backed state that survives restart and can never reset, move
backward, or be replaced with current equity to widen an allowable
limit (AC-M08-W04-02):

- the high-water mark only ever moves up (compare-and-set);
- the day-start equity for a date is first-write-wins — a later same-day
  value can never replace it;
- the consecutive-loss streak derives from recorded day results and only
  resets to zero on an evidence-backed profitable day;
- before the first recorded day every read returns ``None`` so the
  configured rules fail closed instead of silently disabling themselves
  (AC-M08-W04-03).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_core import paths as _paths
from pydantic import BaseModel, ConfigDict, Field, field_validator

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS account_loss_state (
    account_id         TEXT PRIMARY KEY,
    high_water_mark    TEXT,
    consecutive_losses BIGINT,
    updated_at         TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS account_day_results (
    account_id       TEXT NOT NULL,
    day_date         DATE NOT NULL,
    day_start_equity TEXT NOT NULL,
    end_equity       TEXT NOT NULL,
    pnl              TEXT NOT NULL,
    recorded_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (account_id, day_date)
);
CREATE TABLE IF NOT EXISTS daily_loss_blocks (
    account_id TEXT NOT NULL,
    day_date DATE NOT NULL,
    triggered_at TIMESTAMPTZ NOT NULL,
    realized_pnl TEXT NOT NULL,
    unrealized_pnl TEXT NOT NULL,
    nav TEXT NOT NULL,
    ceiling_pct TEXT NOT NULL,
    PRIMARY KEY (account_id, day_date)
);
CREATE TABLE IF NOT EXISTS closed_trade_loss_results (
    account_id TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    closed_at TIMESTAMPTZ NOT NULL,
    closing_transaction_id TEXT NOT NULL,
    pnl TEXT NOT NULL,
    PRIMARY KEY (account_id, trade_id)
);
CREATE TABLE IF NOT EXISTS symbol_loss_state (
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    consecutive_losses BIGINT NOT NULL,
    frozen_until TIMESTAMPTZ,
    last_trade_id TEXT NOT NULL,
    last_close_transaction_id TEXT NOT NULL,
    PRIMARY KEY (account_id, symbol)
);
CREATE TABLE IF NOT EXISTS closed_trade_observations (
    account_id TEXT PRIMARY KEY,
    last_transaction_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL
);
"""


class DayResultSummary(BaseModel):
    """One deterministic day-result record verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    day_date: date
    day_start_equity: Decimal
    end_equity: Decimal
    pnl: Decimal
    high_water_mark: Decimal | None
    consecutive_losses: int | None
    recorded: bool


class ClosedTradeResult(BaseModel):
    """One fully closed broker trade; P&L includes all its partial closures."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    trade_id: str = Field(pattern=r"^[1-9][0-9]*$")
    symbol: str = Field(min_length=1)
    closed_at: datetime
    closing_transaction_id: str = Field(pattern=r"^[1-9][0-9]*$")
    pnl: Decimal

    @field_validator("pnl", mode="before")
    @classmethod
    def _money(cls, value: Any) -> Decimal:
        if isinstance(value, (float, bool)):
            raise ValueError("closed P&L must not be float or bool")
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("closed P&L must be finite")
        return result

    @field_validator("closed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("closed time must be aware")
        return value.astimezone(UTC)


class SymbolLossState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    consecutive_losses: int
    frozen_until: datetime | None
    last_trade_id: str
    last_close_transaction_id: str


class LossStateStore:
    """DuckDB-backed durable loss state with compare-and-set semantics."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _paths.db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLES)

    def observe_daily_loss(
        self,
        account_id: str,
        *,
        observed_at: datetime,
        realized_pnl: Decimal,
        unrealized_pnl: Decimal,
        nav: Decimal,
        ceiling_pct: Decimal,
    ) -> bool:
        """Latch a broker-evidenced loss breach for the whole UTC day."""
        if not account_id.strip() or observed_at.tzinfo is None:
            raise ValueError("account and aware observation time required")
        breached = daily_loss_breached(realized_pnl, unrealized_pnl, nav, ceiling_pct)
        stamp = observed_at.astimezone(UTC)
        if breached:
            self._conn.execute(
                """INSERT INTO daily_loss_blocks VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (account_id, day_date) DO NOTHING""",
                [
                    account_id,
                    stamp.date(),
                    stamp,
                    str(realized_pnl),
                    str(unrealized_pnl),
                    str(nav),
                    str(ceiling_pct),
                ],
            )
        return self.daily_loss_blocked(account_id, stamp.date())

    def daily_loss_blocked(self, account_id: str, day_date: date) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM daily_loss_blocks WHERE account_id = ? AND day_date = ?",
                [account_id, day_date],
            ).fetchone()
            is not None
        )

    def observe_closed_trades(
        self,
        account_id: str,
        *,
        trades: tuple[ClosedTradeResult, ...],
        observed_at: datetime,
        last_transaction_id: str,
    ) -> dict[str, SymbolLossState]:
        """Atomically reconcile complete immutable history and derive rule 12.

        Broker close transaction order is authoritative. Re-reading a trade
        never creates a new loss or moves its original 24-hour deadline.
        """
        if (
            not account_id.strip()
            or observed_at.tzinfo is None
            or not last_transaction_id.isdigit()
            or int(last_transaction_id) <= 0
        ):
            raise ValueError("account and aware observation time required")
        incoming = {trade.trade_id: trade for trade in trades}
        if len(incoming) != len(trades) or any(
            trade.closed_at > observed_at
            or int(trade.closing_transaction_id) <= int(trade.trade_id)
            or trade.symbol != trade.symbol.strip().upper()
            or int(trade.closing_transaction_id) > int(last_transaction_id)
            for trade in trades
        ):
            raise ValueError("closed trade history invalid")
        ordered = sorted(
            trades,
            key=lambda t: (
                int(t.closing_transaction_id),
                int(t.trade_id),
            ),
        )
        states: dict[str, SymbolLossState] = {}
        self._conn.execute("BEGIN")
        try:
            observation = self._conn.execute(
                """SELECT last_transaction_id FROM closed_trade_observations
                   WHERE account_id = ?""",
                [account_id],
            ).fetchone()
            previous_watermark = None if observation is None else int(observation[0])
            if (
                previous_watermark is not None
                and int(last_transaction_id) < previous_watermark
            ):
                raise ValueError("closed history watermark moved backward")
            prior = self._conn.execute(
                """SELECT trade_id, symbol, closed_at, closing_transaction_id, pnl
                   FROM closed_trade_loss_results WHERE account_id = ?""",
                [account_id],
            ).fetchall()
            prior_ids = {row[0] for row in prior}
            if previous_watermark is not None and any(
                trade.trade_id not in prior_ids
                and int(trade.closing_transaction_id) <= previous_watermark
                for trade in trades
            ):
                raise ValueError("previous complete history omitted a closed trade")
            for identity, symbol, stamp, close_id, pnl in prior:
                trade = incoming.get(identity)
                if (
                    trade is None
                    or trade.symbol != symbol
                    or trade.closed_at != stamp
                    or trade.closing_transaction_id != close_id
                    or trade.pnl != Decimal(pnl)
                ):
                    raise ValueError("closed history changed or lost prior evidence")
            last_time: datetime | None = None
            for trade in ordered:
                if last_time is not None and trade.closed_at < last_time:
                    raise ValueError("close time contradicts broker transaction order")
                last_time = trade.closed_at
                self._conn.execute(
                    """INSERT INTO closed_trade_loss_results VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT (account_id, trade_id) DO NOTHING""",
                    [
                        account_id,
                        trade.trade_id,
                        trade.symbol,
                        trade.closed_at,
                        trade.closing_transaction_id,
                        str(trade.pnl),
                    ],
                )
                current = states.get(trade.symbol)
                losses = 0 if current is None else current.consecutive_losses
                losses = losses + 1 if trade.pnl < 0 else 0
                deadline = None if current is None else current.frozen_until
                if losses >= 3:
                    triggered_until = trade.closed_at + timedelta(hours=24)
                    deadline = (
                        max(deadline, triggered_until) if deadline else triggered_until
                    )
                states[trade.symbol] = SymbolLossState(
                    consecutive_losses=losses,
                    frozen_until=deadline,
                    last_trade_id=trade.trade_id,
                    last_close_transaction_id=trade.closing_transaction_id,
                )
            for symbol, state in states.items():
                previous_state = self.symbol_state(account_id, symbol)
                if (
                    previous_state is not None
                    and previous_state.frozen_until is not None
                ):
                    deadline = previous_state.frozen_until
                    state = state.model_copy(
                        update={
                            "frozen_until": (
                                deadline
                                if state.frozen_until is None
                                else max(deadline, state.frozen_until)
                            )
                        }
                    )
                    states[symbol] = state
                self._conn.execute(
                    """INSERT INTO symbol_loss_state VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT (account_id, symbol) DO UPDATE SET
                       consecutive_losses = EXCLUDED.consecutive_losses,
                       frozen_until = EXCLUDED.frozen_until,
                       last_trade_id = EXCLUDED.last_trade_id,
                       last_close_transaction_id =
                           EXCLUDED.last_close_transaction_id""",
                    [
                        account_id,
                        symbol,
                        state.consecutive_losses,
                        state.frozen_until,
                        state.last_trade_id,
                        state.last_close_transaction_id,
                    ],
                )
            self._conn.execute(
                """INSERT INTO closed_trade_observations VALUES (?, ?, ?)
                   ON CONFLICT (account_id) DO UPDATE SET
                   last_transaction_id = EXCLUDED.last_transaction_id,
                   observed_at = EXCLUDED.observed_at""",
                [account_id, last_transaction_id, observed_at.astimezone(UTC)],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return states

    def symbol_state(self, account_id: str, symbol: str) -> SymbolLossState | None:
        row = self._conn.execute(
            """SELECT consecutive_losses, frozen_until, last_trade_id,
                      last_close_transaction_id FROM symbol_loss_state
               WHERE account_id = ? AND symbol = ?""",
            [account_id, symbol],
        ).fetchone()
        if row is None:
            return None
        return SymbolLossState(
            consecutive_losses=row[0],
            frozen_until=row[1],
            last_trade_id=row[2],
            last_close_transaction_id=row[3],
        )

    def record_day_result(
        self,
        account_id: str,
        *,
        day_date: date,
        day_start_equity: Decimal,
        end_equity: Decimal,
        owner: str,
    ) -> DayResultSummary:
        """Record one day result with forward-only state updates.

        The day-start equity for a date is first-write-wins; the
        high-water mark never moves down; the loss streak increments on
        a losing day and resets to zero on a profitable day.
        """
        if not account_id.strip():
            raise ValueError("account_id must not be empty")
        now = datetime.now(UTC)
        current_hwm = self.high_water_mark(account_id)
        current_streak = self.consecutive_losses(account_id)

        self._conn.execute("BEGIN")
        try:
            inserted = self._conn.execute(
                """
                INSERT INTO account_day_results (
                    account_id, day_date, day_start_equity, end_equity,
                    pnl, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (account_id, day_date) DO NOTHING
                """,
                [
                    account_id,
                    day_date,
                    str(day_start_equity),
                    str(end_equity),
                    str(end_equity - day_start_equity),
                    now,
                ],
            ).fetchone()
            recorded = bool(inserted and inserted[0] > 0)
            # The authoritative day start is the first recorded value.
            row = self._conn.execute(
                """SELECT day_start_equity, end_equity, pnl
                   FROM account_day_results
                   WHERE account_id = ? AND day_date = ?""",
                [account_id, day_date],
            ).fetchone()
            assert row is not None
            start = Decimal(str(row[0]))
            end = Decimal(str(row[1]))
            pnl = Decimal(str(row[2]))

            new_streak: int | None
            if current_streak is None:
                new_streak = 1 if pnl < 0 else 0
            else:
                new_streak = current_streak + 1 if pnl < 0 else 0
            new_hwm = end if current_hwm is None else max(current_hwm, end)
            self._conn.execute(
                """
                INSERT INTO account_loss_state (
                    account_id, high_water_mark, consecutive_losses, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (account_id) DO UPDATE SET
                    high_water_mark = EXCLUDED.high_water_mark,
                    consecutive_losses = EXCLUDED.consecutive_losses,
                    updated_at = EXCLUDED.updated_at
                """,
                [account_id, str(new_hwm), new_streak, now],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return DayResultSummary(
            account_id=account_id,
            day_date=day_date,
            day_start_equity=start,
            end_equity=end,
            pnl=pnl,
            high_water_mark=new_hwm,
            consecutive_losses=new_streak,
            recorded=recorded,
        )

    def high_water_mark(self, account_id: str) -> Decimal | None:
        row = self._conn.execute(
            "SELECT high_water_mark FROM account_loss_state WHERE account_id = ?",
            [account_id],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return Decimal(str(row[0]))

    def day_start(self, account_id: str, day_date: date) -> Decimal | None:
        row = self._conn.execute(
            """SELECT day_start_equity FROM account_day_results
               WHERE account_id = ? AND day_date = ?""",
            [account_id, day_date],
        ).fetchone()
        if row is None:
            return None
        return Decimal(str(row[0]))

    def consecutive_losses(self, account_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT consecutive_losses FROM account_loss_state WHERE account_id = ?",
            [account_id],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def day_results(self, account_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT day_date, day_start_equity, end_equity, pnl, recorded_at
               FROM account_day_results WHERE account_id = ?
               ORDER BY day_date""",
            [account_id],
        ).fetchall()
        return [
            {
                "day_date": str(row[0]),
                "day_start_equity": str(row[1]),
                "end_equity": str(row[2]),
                "pnl": str(row[3]),
                "recorded_at": str(row[4]),
            }
            for row in rows
        ]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


def daily_loss_breached(
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
    nav: Decimal,
    ceiling_pct: Decimal,
) -> bool:
    """Rule 10: loss must be strictly less than the current NAV fraction."""
    values = (realized_pnl, unrealized_pnl, nav, ceiling_pct)
    if any(not isinstance(v, Decimal) or not v.is_finite() for v in values):
        raise ValueError("daily loss requires finite Decimal facts")
    if nav <= 0 or not 0 < ceiling_pct <= 1:
        raise ValueError("daily loss requires positive NAV and a valid fraction")
    return -(realized_pnl + unrealized_pnl) >= nav * ceiling_pct


__all__ = ["DayResultSummary", "LossStateStore", "daily_loss_breached"]
