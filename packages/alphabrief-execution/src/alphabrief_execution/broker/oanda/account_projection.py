"""Durable remote account projections (M07-W03).

Derives account, balance, NAV, margin, order, fill, trade, position,
realized/unrealized PnL, and financing projections from immutable OANDA
facts with broker IDs and UTC timestamps. A clean replay of the golden
fact history and a full-snapshot-plus-incremental-changes path converge
to the same normalized projection. API, CLI, and scheduler readers
resolve the same persisted account authority — never conflicting
process-local portfolio state.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Deterministic margin rate used for position margin projections.
DEFAULT_MARGIN_RATE = Decimal("0.05")

FactKind = Literal[
    "ORDER_CREATE",
    "ORDER_FILL",
    "ORDER_CANCEL",
    "TRADE_CLOSE",
    "TRADE_REDUCE",
    "DAILY_FINANCING",
    "DEPOSIT",
    "WITHDRAWAL",
]

#: Facts with no effect on the supported projection surface.
_IGNORED_KINDS: frozenset[str] = frozenset(
    {"CLIENT_CONFIGURE", "MARGIN_CALL_ENTER", "MARGIN_CALL_EXIT"}
)


class ProjectionFact(BaseModel):
    """One immutable broker fact for projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str = Field(min_length=1)
    kind: FactKind
    order_id: str | None = None
    trade_id: str | None = None
    instrument: str | None = None
    units: Decimal = Decimal("0")
    price: Decimal | None = None
    realized_pl: Decimal = Decimal("0")
    financing: Decimal = Decimal("0")
    occurred_at: datetime

    @field_validator("units", "realized_pl", "financing", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("projection fact numeric fields must not be floats")
        return value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def time_must_be_utc(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise ValueError("occurred_at must be a datetime")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


class OrderProjection(BaseModel):
    """One projected order state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_order_id: str
    instrument: str | None = None
    units: Decimal
    state: str
    price: Decimal | None = None
    client_order_id: str | None = None


class TradeProjection(BaseModel):
    """One projected trade state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_trade_id: str
    instrument: str | None = None
    current_units: Decimal
    average_price: Decimal | None = None
    realized_pl: Decimal
    financing: Decimal
    state: str
    open_time: datetime | None = None


class PositionProjection(BaseModel):
    """One projected position with distinct sides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument: str
    long_units: Decimal
    short_units: Decimal
    long_average_price: Decimal | None = None
    short_average_price: Decimal | None = None
    unrealized_pl: Decimal


class FillProjection(BaseModel):
    """One projected fill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    order_id: str | None = None
    trade_id: str | None = None
    instrument: str | None = None
    units: Decimal
    price: Decimal | None = None
    realized_pl: Decimal
    financing: Decimal
    occurred_at: datetime


class AccountSnapshot(BaseModel):
    """The deterministic normalized projection of one account."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    last_transaction_id: str = "0"
    balance: Decimal
    nav: Decimal
    unrealized_pl: Decimal
    margin_used: Decimal
    margin_available: Decimal
    realized_pl: Decimal
    financing_total: Decimal
    open_trade_count: int
    open_position_count: int
    orders: tuple[OrderProjection, ...]
    trades: tuple[TradeProjection, ...]
    positions: tuple[PositionProjection, ...]
    fills: tuple[FillProjection, ...]
    rebuilt_at: datetime


class _ProjectionState:
    """Mutable fold state; never exposed outside the store."""

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.balance = Decimal("0")
        self.realized_pl = Decimal("0")
        self.financing_total = Decimal("0")
        self.orders: dict[str, OrderProjection] = {}
        self.trades: dict[str, TradeProjection] = {}
        self.fills: list[FillProjection] = []
        self.last_price: dict[str, Decimal] = {}
        self.last_transaction_id = "0"

    def apply(self, fact: ProjectionFact) -> None:
        """Fold one fact deterministically into the state."""
        if fact.kind in _IGNORED_KINDS:
            return
        fact_id = fact.fact_id
        if fact_id.isdigit() and int(fact_id) > int(self.last_transaction_id):
            self.last_transaction_id = fact_id
        if fact.kind == "ORDER_CREATE":
            if fact.order_id is not None:
                self.orders[fact.order_id] = OrderProjection(
                    broker_order_id=fact.order_id,
                    instrument=fact.instrument,
                    units=fact.units,
                    state="PENDING",
                    price=fact.price,
                )
            return
        if fact.kind == "ORDER_CANCEL":
            if fact.order_id is not None and fact.order_id in self.orders:
                order = self.orders[fact.order_id]
                self.orders[fact.order_id] = order.model_copy(
                    update={"state": "CANCELLED"}
                )
            return
        if fact.kind == "ORDER_FILL":
            self._apply_fill(fact)
            return
        if fact.kind == "TRADE_CLOSE":
            self._close_trade(fact)
            return
        if fact.kind == "TRADE_REDUCE":
            self._reduce_trade(fact)
            return
        if fact.kind == "DAILY_FINANCING":
            self.balance += fact.financing
            self.financing_total += fact.financing
            return
        if fact.kind == "DEPOSIT":
            self.balance += fact.units
            return
        if fact.kind == "WITHDRAWAL":
            self.balance -= fact.units
            return

    # ------------------------------------------------------------------
    # Fact handlers
    # ------------------------------------------------------------------

    def _apply_fill(self, fact: ProjectionFact) -> None:
        if fact.order_id is not None and fact.order_id in self.orders:
            order = self.orders[fact.order_id]
            self.orders[fact.order_id] = order.model_copy(
                update={"state": "FILLED", "price": fact.price or order.price}
            )
        if fact.instrument is not None and fact.price is not None:
            self.last_price[fact.instrument] = fact.price
        self.fills.append(
            FillProjection(
                fact_id=fact.fact_id,
                order_id=fact.order_id,
                trade_id=fact.trade_id,
                instrument=fact.instrument,
                units=fact.units,
                price=fact.price,
                realized_pl=fact.realized_pl,
                financing=fact.financing,
                occurred_at=fact.occurred_at,
            )
        )
        self.balance += fact.realized_pl
        self.balance += fact.financing
        self.realized_pl += fact.realized_pl
        self.financing_total += fact.financing
        if fact.trade_id is None:
            return
        trade = self.trades.get(fact.trade_id)
        if trade is None:
            self.trades[fact.trade_id] = TradeProjection(
                broker_trade_id=fact.trade_id,
                instrument=fact.instrument,
                current_units=fact.units,
                average_price=fact.price,
                realized_pl=fact.realized_pl,
                financing=fact.financing,
                state="OPEN",
                open_time=fact.occurred_at,
            )
            return
        # A fill on an existing trade reduces or closes it.
        remaining = trade.current_units + fact.units
        if (trade.current_units > 0 and remaining < 0) or (
            trade.current_units < 0 and remaining > 0
        ):
            remaining = Decimal("0")
        state = "CLOSED" if remaining == 0 else "OPEN"
        self.trades[fact.trade_id] = trade.model_copy(
            update={
                "current_units": remaining,
                "realized_pl": trade.realized_pl + fact.realized_pl,
                "financing": trade.financing + fact.financing,
                "state": state,
            }
        )

    def _close_trade(self, fact: ProjectionFact) -> None:
        if fact.instrument is not None and fact.price is not None:
            # The close price is the latest market observation.
            self.last_price[fact.instrument] = fact.price
        if fact.trade_id is None or fact.trade_id not in self.trades:
            return
        trade = self.trades[fact.trade_id]
        self.balance += fact.realized_pl
        self.balance += fact.financing
        self.realized_pl += fact.realized_pl
        self.financing_total += fact.financing
        self.trades[fact.trade_id] = trade.model_copy(
            update={
                "current_units": Decimal("0"),
                "state": "CLOSED",
                "realized_pl": trade.realized_pl + fact.realized_pl,
                "financing": trade.financing + fact.financing,
            }
        )

    def _reduce_trade(self, fact: ProjectionFact) -> None:
        if fact.instrument is not None and fact.price is not None:
            self.last_price[fact.instrument] = fact.price
        if fact.trade_id is None or fact.trade_id not in self.trades:
            return
        trade = self.trades[fact.trade_id]
        remaining = trade.current_units + fact.units
        if (trade.current_units > 0 and remaining < 0) or (
            trade.current_units < 0 and remaining > 0
        ):
            remaining = Decimal("0")
        self.balance += fact.realized_pl
        self.realized_pl += fact.realized_pl
        self.trades[fact.trade_id] = trade.model_copy(
            update={
                "current_units": remaining,
                "realized_pl": trade.realized_pl + fact.realized_pl,
                "state": "CLOSED" if remaining == 0 else "OPEN",
            }
        )

    # ------------------------------------------------------------------
    # Snapshot assembly
    # ------------------------------------------------------------------

    def snapshot(self) -> AccountSnapshot:
        positions: dict[str, PositionProjection] = {}
        for trade in self.trades.values():
            if trade.state != "OPEN" or trade.instrument is None:
                continue
            position = positions.setdefault(
                trade.instrument,
                PositionProjection(
                    instrument=trade.instrument,
                    long_units=Decimal("0"),
                    short_units=Decimal("0"),
                    unrealized_pl=Decimal("0"),
                ),
            )
            price = trade.average_price or self.last_price.get(
                trade.instrument, Decimal("0")
            )
            if trade.current_units > 0:
                position = position.model_copy(
                    update={
                        "long_units": position.long_units + trade.current_units,
                        "long_average_price": price,
                    }
                )
            else:
                position = position.model_copy(
                    update={
                        "short_units": position.short_units
                        + abs(trade.current_units),
                        "short_average_price": price,
                    }
                )
            positions[trade.instrument] = position

        # Per-position unrealized PnL against the last observed mark.
        rebuilt_positions: dict[str, PositionProjection] = {}
        for instrument, position in positions.items():
            mark = self.last_price.get(instrument)
            position_unrealized = Decimal("0")
            if mark is not None:
                if position.long_units > 0 and position.long_average_price:
                    position_unrealized += (
                        (mark - position.long_average_price) * position.long_units
                    )
                if position.short_units > 0 and position.short_average_price:
                    position_unrealized += (
                        (position.short_average_price - mark) * position.short_units
                    )
            rebuilt_positions[instrument] = position.model_copy(
                update={"unrealized_pl": position_unrealized}
            )

        margin_used = Decimal("0")
        for position in rebuilt_positions.values():
            notional = Decimal("0")
            if position.long_units > 0 and position.long_average_price:
                notional += position.long_units * position.long_average_price
            if position.short_units > 0 and position.short_average_price:
                notional += position.short_units * position.short_average_price
            margin_used += notional * DEFAULT_MARGIN_RATE

        nav = self.balance + sum(
            (p.unrealized_pl for p in rebuilt_positions.values()),
            Decimal("0"),
        )
        open_trades = [t for t in self.trades.values() if t.state == "OPEN"]
        return AccountSnapshot(
            account_id=self.account_id,
            last_transaction_id=self.last_transaction_id,
            balance=self.balance,
            nav=nav,
            unrealized_pl=sum(
                (p.unrealized_pl for p in rebuilt_positions.values()),
                Decimal("0"),
            ),
            margin_used=margin_used,
            margin_available=nav - margin_used,
            realized_pl=self.realized_pl,
            financing_total=self.financing_total,
            open_trade_count=len(open_trades),
            open_position_count=len(rebuilt_positions),
            orders=tuple(self.orders.values()),
            trades=tuple(self.trades.values()),
            positions=tuple(rebuilt_positions.values()),
            fills=tuple(self.fills),
            rebuilt_at=datetime.now(UTC),
        )


def fold_facts(
    account_id: str, facts: list[ProjectionFact]
) -> AccountSnapshot:
    """Fold facts in broker-ID order into one deterministic snapshot."""
    state = _ProjectionState(account_id)
    ordered = sorted(
        facts, key=lambda f: int(f.fact_id) if f.fact_id.isdigit() else 0
    )
    for fact in ordered:
        state.apply(fact)
    return state.snapshot()


class AccountProjectionStore:
    """DuckDB-backed durable account projection store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_projections (
                account_id      TEXT PRIMARY KEY,
                last_transaction_id TEXT NOT NULL,
                state_json      TEXT NOT NULL,
                rebuilt_at      TIMESTAMPTZ NOT NULL
            )
            """
        )

    def rebuild(
        self,
        account_id: str,
        facts: list[ProjectionFact],
        *,
        initial_balance: Decimal = Decimal("0"),
    ) -> AccountSnapshot:
        """Rebuild the projection from a clean replay of all facts.

        The initial balance seeds the fold; every supported fact type is
        applied deterministically in broker-ID order.
        """
        snapshot = fold_facts(account_id, facts)
        snapshot = snapshot.model_copy(
            update={
                "balance": snapshot.balance + initial_balance,
                "nav": snapshot.nav + initial_balance,
                "margin_available": snapshot.margin_available + initial_balance,
            }
        )
        self._persist(account_id, snapshot)
        return snapshot

    def apply_changes(
        self,
        account_id: str,
        facts: list[ProjectionFact],
    ) -> AccountSnapshot:
        """Apply incremental facts on top of the persisted snapshot.

        The resulting projection must equal a clean replay of the full
        fact history (AC-M07-W03-02).
        """
        current = self.snapshot(account_id)
        state = _ProjectionState(account_id)
        if current is not None:
            state.balance = current.balance
            state.realized_pl = current.realized_pl
            state.financing_total = current.financing_total
            state.last_transaction_id = current.last_transaction_id
            state.orders = {o.broker_order_id: o for o in current.orders}
            state.trades = {t.broker_trade_id: t for t in current.trades}
            state.fills = list(current.fills)
        for fact in sorted(
            facts, key=lambda f: int(f.fact_id) if f.fact_id.isdigit() else 0
        ):
            state.apply(fact)
        snapshot = state.snapshot()
        self._persist(account_id, snapshot)
        return snapshot

    def snapshot(self, account_id: str) -> AccountSnapshot | None:
        row = self._conn.execute(
            """SELECT last_transaction_id, state_json
               FROM account_projections WHERE account_id = ?""",
            [account_id],
        ).fetchone()
        if row is None:
            return None
        return AccountSnapshot.model_validate_json(str(row[1]))

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def _persist(self, account_id: str, snapshot: AccountSnapshot) -> None:
        self._conn.execute(
            """
            INSERT INTO account_projections (
                account_id, last_transaction_id, state_json, rebuilt_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT (account_id) DO UPDATE SET
                last_transaction_id = EXCLUDED.last_transaction_id,
                state_json = EXCLUDED.state_json,
                rebuilt_at = EXCLUDED.rebuilt_at
            """,
            [
                account_id,
                snapshot.last_transaction_id,
                snapshot.model_dump_json(),
                datetime.now(UTC),
            ],
        )


def resolve_account_snapshot(
    account_id: str,
    db_path: Path | str | None = None,
) -> AccountSnapshot | None:
    """The single persisted account authority for API/CLI/scheduler readers.

    Every reader resolves the same store file, so process-local
    portfolio state can never conflict with the persisted authority.
    """
    store = AccountProjectionStore(db_path=db_path)
    try:
        return store.snapshot(account_id)
    finally:
        store.close()


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "AccountProjectionStore",
    "AccountSnapshot",
    "DEFAULT_MARGIN_RATE",
    "FillProjection",
    "OrderProjection",
    "PositionProjection",
    "ProjectionFact",
    "TradeProjection",
    "fold_facts",
    "resolve_account_snapshot",
]
