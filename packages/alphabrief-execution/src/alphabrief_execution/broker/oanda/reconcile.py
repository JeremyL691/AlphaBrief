"""OANDA account reconciliation without false mismatches (M07-W04).

Compares the local durable projection (M07-W03) with a remote OANDA
view across orders, trades, positions, balance, NAV, margin, financing,
fills, and the transaction cursor. Legitimate broker-originated remote
state (orders, trades, positions without our client identity) and
matched ledger identities reconcile without false missing-local alarms.
Every real difference produces a stable typed diff with source IDs and
severity. Decimal and timestamp tolerances are explicit, versioned, and
directionally safe: they can never hide a material exposure, cash,
margin, or position shortfall.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.oanda.account_projection import AccountSnapshot
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger

DiffKind = Literal[
    "account_diff",
    "cursor_diff",
    "order_diff",
    "trade_diff",
    "position_diff",
    "money_diff",
    "quantity_diff",
    "state_diff",
    "fill_diff",
]

Severity = Literal["INFO", "WARN", "CRITICAL"]

#: The versioned default tolerance set (explicit and directionally safe).
DEFAULT_TOLERANCE_VERSION = "2026-08-13.1"


class RemoteOrder(BaseModel):
    """One remote order as reported by the broker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_order_id: str = Field(min_length=1)
    state: str = Field(min_length=1)
    units: Decimal
    client_order_id: str | None = None
    create_time: datetime | None = None


class RemoteTrade(BaseModel):
    """One remote trade as reported by the broker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_trade_id: str = Field(min_length=1)
    state: str = Field(min_length=1)
    current_units: Decimal
    client_order_id: str | None = None


class RemotePosition(BaseModel):
    """One remote position as reported by the broker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument: str = Field(min_length=1)
    long_units: Decimal
    short_units: Decimal


class RemoteAccountView(BaseModel):
    """One remote OANDA view for reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    orders: tuple[RemoteOrder, ...] = ()
    trades: tuple[RemoteTrade, ...] = ()
    positions: tuple[RemotePosition, ...] = ()
    balance: Decimal = Decimal("0")
    nav: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    financing_total: Decimal = Decimal("0")
    remote_fill_count: int = 0
    last_transaction_id: str = "0"


class ReconcileTolerances(BaseModel):
    """Explicit, versioned, directionally safe comparison tolerances."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tolerance_version: str = DEFAULT_TOLERANCE_VERSION
    money_tolerance: Decimal = Decimal("0.01")
    # Quantity is never tolerated: a single unit difference is a
    # material exposure difference and must always be reported.
    quantity_tolerance: Decimal = Decimal("0")
    timestamp_tolerance_seconds: int = 5


class DiffRecord(BaseModel):
    """One stable typed reconciliation difference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DiffKind
    source_id: str = Field(min_length=1)
    severity: Severity
    detail: str
    local_value: str | None = None
    remote_value: str | None = None


class ReconciliationReport(BaseModel):
    """One deterministic reconciliation verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    tolerance_version: str = Field(min_length=1)
    diffs: tuple[DiffRecord, ...]
    compared_at: datetime

    @property
    def clean(self) -> bool:
        """Clean means no WARN or CRITICAL differences remain."""
        return all(diff.severity == "INFO" for diff in self.diffs)


class Reconciler:
    """Compares the local projection with a remote view deterministically."""

    def __init__(
        self,
        tolerances: ReconcileTolerances | None = None,
    ) -> None:
        self._tolerances = tolerances or ReconcileTolerances()

    def reconcile(
        self,
        local: AccountSnapshot,
        remote: RemoteAccountView,
        *,
        ledger: OrderLedger | None = None,
    ) -> ReconciliationReport:
        """Reconcile one local projection against one remote view."""
        diffs: list[DiffRecord] = []

        self._check_account(local, remote, diffs)
        self._check_cursor(local, remote, diffs)
        self._check_orders(local, remote, ledger, diffs)
        self._check_trades(local, remote, ledger, diffs)
        self._check_positions(local, remote, diffs)
        self._check_money(local, remote, diffs)
        self._check_fills(local, remote, diffs)

        return ReconciliationReport(
            account_id=local.account_id,
            tolerance_version=self._tolerances.tolerance_version,
            diffs=tuple(diffs),
            compared_at=datetime.now(UTC),
        )

    # ------------------------------------------------------------------
    # Comparison passes
    # ------------------------------------------------------------------

    def _check_account(
        self,
        local: AccountSnapshot,
        remote: RemoteAccountView,
        diffs: list[DiffRecord],
    ) -> None:
        if local.account_id != remote.account_id:
            diffs.append(
                DiffRecord(
                    kind="account_diff",
                    source_id=remote.account_id,
                    severity="CRITICAL",
                    detail="local and remote account IDs differ",
                    local_value=local.account_id,
                    remote_value=remote.account_id,
                )
            )

    def _check_cursor(
        self,
        local: AccountSnapshot,
        remote: RemoteAccountView,
        diffs: list[DiffRecord],
    ) -> None:
        local_cursor = int(local.last_transaction_id)
        remote_cursor = int(remote.last_transaction_id)
        if remote_cursor < local_cursor:
            diffs.append(
                DiffRecord(
                    kind="cursor_diff",
                    source_id=remote.last_transaction_id,
                    severity="CRITICAL",
                    detail="broker cursor is behind the local committed cursor",
                    local_value=local.last_transaction_id,
                    remote_value=remote.last_transaction_id,
                )
            )
        elif remote_cursor > local_cursor:
            diffs.append(
                DiffRecord(
                    kind="cursor_diff",
                    source_id=remote.last_transaction_id,
                    severity="INFO",
                    detail="remote cursor ahead: pending consumption, not a mismatch",
                    local_value=local.last_transaction_id,
                    remote_value=remote.last_transaction_id,
                )
            )

    def _check_orders(
        self,
        local: AccountSnapshot,
        remote: RemoteAccountView,
        ledger: OrderLedger | None,
        diffs: list[DiffRecord],
    ) -> None:
        local_orders = {order.broker_order_id: order for order in local.orders}
        for remote_order in remote.orders:
            order_id = remote_order.broker_order_id
            local_order = local_orders.get(order_id)
            if local_order is None:
                self._unknown_or_broker_originated(
                    kind="order_diff",
                    source_id=order_id,
                    client_order_id=remote_order.client_order_id,
                    ledger=ledger,
                    detail="remote order has no local projection",
                    diffs=diffs,
                )
                continue
            if local_order.state != remote_order.state:
                diffs.append(
                    DiffRecord(
                        kind="state_diff",
                        source_id=order_id,
                        severity="CRITICAL",
                        detail=(
                            f"order state mismatch: local {local_order.state} "
                            f"vs remote {remote_order.state}"
                        ),
                        local_value=local_order.state,
                        remote_value=remote_order.state,
                    )
                )
            if (
                abs(local_order.units - remote_order.units)
                > self._tolerances.quantity_tolerance
            ):
                diffs.append(
                    DiffRecord(
                        kind="quantity_diff",
                        source_id=order_id,
                        severity="CRITICAL",
                        detail="order units differ",
                        local_value=str(local_order.units),
                        remote_value=str(remote_order.units),
                    )
                )
        for order_id, local_order in local_orders.items():
            remote_ids = {o.broker_order_id for o in remote.orders}
            if order_id not in remote_ids:
                diffs.append(
                    DiffRecord(
                        kind="order_diff",
                        source_id=order_id,
                        severity="CRITICAL",
                        detail="local order missing at the broker",
                        local_value=local_order.state,
                        remote_value=None,
                    )
                )

    def _check_trades(
        self,
        local: AccountSnapshot,
        remote: RemoteAccountView,
        ledger: OrderLedger | None,
        diffs: list[DiffRecord],
    ) -> None:
        local_trades = {trade.broker_trade_id: trade for trade in local.trades}
        for remote_trade in remote.trades:
            trade_id = remote_trade.broker_trade_id
            local_trade = local_trades.get(trade_id)
            if local_trade is None:
                self._unknown_or_broker_originated(
                    kind="trade_diff",
                    source_id=trade_id,
                    client_order_id=remote_trade.client_order_id,
                    ledger=ledger,
                    detail="remote trade has no local projection",
                    diffs=diffs,
                )
                continue
            if local_trade.state != remote_trade.state:
                diffs.append(
                    DiffRecord(
                        kind="state_diff",
                        source_id=trade_id,
                        severity="CRITICAL",
                        detail=(
                            f"trade state mismatch: local {local_trade.state} "
                            f"vs remote {remote_trade.state}"
                        ),
                        local_value=local_trade.state,
                        remote_value=remote_trade.state,
                    )
                )
            if (
                abs(local_trade.current_units - remote_trade.current_units)
                > self._tolerances.quantity_tolerance
            ):
                diffs.append(
                    DiffRecord(
                        kind="quantity_diff",
                        source_id=trade_id,
                        severity="CRITICAL",
                        detail="trade open units differ",
                        local_value=str(local_trade.current_units),
                        remote_value=str(remote_trade.current_units),
                    )
                )
        for trade_id in local_trades:
            remote_ids = {t.broker_trade_id for t in remote.trades}
            if trade_id not in remote_ids:
                diffs.append(
                    DiffRecord(
                        kind="trade_diff",
                        source_id=trade_id,
                        severity="CRITICAL",
                        detail="local trade missing at the broker",
                    )
                )

    def _check_positions(
        self,
        local: AccountSnapshot,
        remote: RemoteAccountView,
        diffs: list[DiffRecord],
    ) -> None:
        remote_by_instrument = {
            position.instrument: position for position in remote.positions
        }
        for local_position in local.positions:
            if local_position.long_units == 0 and local_position.short_units == 0:
                continue
            remote_position = remote_by_instrument.get(local_position.instrument)
            if remote_position is None:
                diffs.append(
                    DiffRecord(
                        kind="position_diff",
                        source_id=local_position.instrument,
                        severity="CRITICAL",
                        detail="local open position missing at the broker",
                    )
                )
                continue
            long_diff = abs(
                local_position.long_units - remote_position.long_units
            )
            short_diff = abs(
                local_position.short_units - remote_position.short_units
            )
            if (
                long_diff > self._tolerances.quantity_tolerance
                or short_diff > self._tolerances.quantity_tolerance
            ):
                diffs.append(
                    DiffRecord(
                        kind="quantity_diff",
                        source_id=local_position.instrument,
                        severity="CRITICAL",
                        detail="position units differ",
                        local_value=(
                            f"{local_position.long_units}/"
                            f"{local_position.short_units}"
                        ),
                        remote_value=(
                            f"{remote_position.long_units}/"
                            f"{remote_position.short_units}"
                        ),
                    )
                )
        for remote_position in remote.positions:
            if remote_position.long_units == 0 and remote_position.short_units == 0:
                continue
            matched_local = next(
                (
                    p
                    for p in local.positions
                    if p.instrument == remote_position.instrument
                ),
                None,
            )
            if matched_local is None:
                diffs.append(
                    DiffRecord(
                        kind="position_diff",
                        source_id=remote_position.instrument,
                        severity="INFO",
                        detail="broker-originated position (no local projection)",
                        local_value=None,
                        remote_value=(
                            f"{remote_position.long_units}/"
                            f"{remote_position.short_units}"
                        ),
                    )
                )

    def _check_money(
        self,
        local: AccountSnapshot,
        remote: RemoteAccountView,
        diffs: list[DiffRecord],
    ) -> None:
        tolerance = self._tolerances.money_tolerance
        self._money_pass(
            local.balance, remote.balance, "balance", tolerance, diffs
        )
        self._money_pass(local.nav, remote.nav, "nav", tolerance, diffs)
        # Margin is material in both directions: understated local margin
        # (remote higher) is just as dangerous as overstated.
        margin_diff = local.margin_used - remote.margin_used
        if abs(margin_diff) > tolerance:
            diffs.append(
                DiffRecord(
                    kind="money_diff",
                    source_id="margin_used",
                    severity="CRITICAL",
                    detail="margin used differs beyond tolerance",
                    local_value=str(local.margin_used),
                    remote_value=str(remote.margin_used),
                )
            )
        elif margin_diff != 0:
            diffs.append(
                DiffRecord(
                    kind="money_diff",
                    source_id="margin_used",
                    severity="WARN",
                    detail="margin used differs within tolerance",
                    local_value=str(local.margin_used),
                    remote_value=str(remote.margin_used),
                )
            )
        self._money_pass(
            local.financing_total,
            remote.financing_total,
            "financing",
            tolerance,
            diffs,
        )

    def _money_pass(
        self,
        local: Decimal,
        remote: Decimal,
        label: str,
        tolerance: Decimal,
        diffs: list[DiffRecord],
    ) -> None:
        diff = local - remote
        if diff > tolerance:
            diffs.append(
                DiffRecord(
                    kind="money_diff",
                    source_id=label,
                    severity="CRITICAL",
                    detail=f"local {label} exceeds remote beyond tolerance",
                    local_value=str(local),
                    remote_value=str(remote),
                )
            )
        elif diff > 0:
            diffs.append(
                DiffRecord(
                    kind="money_diff",
                    source_id=label,
                    severity="WARN",
                    detail=f"local {label} exceeds remote within tolerance",
                    local_value=str(local),
                    remote_value=str(remote),
                )
            )
        elif diff < 0:
            # Remote richer: favorable windfall, never an alarm.
            diffs.append(
                DiffRecord(
                    kind="money_diff",
                    source_id=label,
                    severity="INFO",
                    detail=f"remote {label} ahead of local",
                    local_value=str(local),
                    remote_value=str(remote),
                )
            )

    def _check_fills(
        self,
        local: AccountSnapshot,
        remote: RemoteAccountView,
        diffs: list[DiffRecord],
    ) -> None:
        local_count = len(local.fills)
        if local_count > remote.remote_fill_count:
            diffs.append(
                DiffRecord(
                    kind="fill_diff",
                    source_id="fills",
                    severity="CRITICAL",
                    detail="local fills exceed remote fills",
                    local_value=str(local_count),
                    remote_value=str(remote.remote_fill_count),
                )
            )
        elif remote.remote_fill_count > local_count:
            diffs.append(
                DiffRecord(
                    kind="fill_diff",
                    source_id="fills",
                    severity="INFO",
                    detail="remote fills ahead: pending consumption",
                    local_value=str(local_count),
                    remote_value=str(remote.remote_fill_count),
                )
            )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _unknown_or_broker_originated(
        self,
        *,
        kind: DiffKind,
        source_id: str,
        client_order_id: str | None,
        ledger: OrderLedger | None,
        detail: str,
        diffs: list[DiffRecord],
    ) -> None:
        if client_order_id is None:
            # No client identity: legitimate broker-originated state.
            diffs.append(
                DiffRecord(
                    kind=kind,
                    source_id=source_id,
                    severity="INFO",
                    detail=f"{detail} (broker-originated, no client identity)",
                    remote_value=client_order_id,
                )
            )
            return
        if ledger is not None and ledger.reservation(client_order_id) is not None:
            # The client identity maps to our own ledger: matched.
            return
        diffs.append(
            DiffRecord(
                kind=kind,
                source_id=source_id,
                severity="CRITICAL",
                detail=f"{detail} (unknown client identity {client_order_id!r})",
                remote_value=client_order_id,
            )
        )


__all__ = [
    "DEFAULT_TOLERANCE_VERSION",
    "DiffKind",
    "DiffRecord",
    "ReconcileTolerances",
    "ReconciliationReport",
    "Reconciler",
    "RemoteAccountView",
    "RemoteOrder",
    "RemotePosition",
    "RemoteTrade",
    "Severity",
]
