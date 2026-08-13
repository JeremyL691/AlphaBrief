"""Operational portfolio resources backed by shared runtime authorities.

Every value is read from (or derived from) the persisted runtime
stores — the paper portfolio and equity snapshots, the broker order
ledger, and the instrument catalog. Nothing is computed in route-local
state and no offline-success placeholder is produced: fields the
runtime stores do not carry are explicit ``null`` (REQ-EXEC-010,
REQ-UI-007).
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from alphabrief_execution.broker.oanda.taxonomy import classify_instrument
from alphabrief_execution.broker.recon_store import BrokerReconStore
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore
from alphabrief_api.db.paper import PaperStore

router = APIRouter(prefix="/api/v1/operational", tags=["operational"])


class OperationalPosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    quantity: str
    average_price: str


class OperationalExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    gross_exposure: str
    net_exposure: str


class OperationalCategoryRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str
    gross_exposure: str
    net_exposure: str


class OperationalOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_order_id: str
    broker_order_id: str
    status: str


class OperationalFill(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    order_id: str | None
    message: str
    created_at: str


class PortfolioOperationalResponse(BaseModel):
    """One typed portfolio resource read from the runtime stores.

    ``margin_used``, ``financing``, and ``category_attribution`` are
    ``null`` when the runtime stores cannot supply or derive them —
    never fabricated.
    """

    model_config = ConfigDict(frozen=True)

    account_id: str
    snapshot_id: str | None
    observed_at: str | None
    cash: str | None
    nav: str | None
    realized_pnl: str | None
    unrealized_pnl: str | None
    margin_used: str | None
    exposure: OperationalExposure | None
    positions: list[OperationalPosition]
    pending_orders: list[OperationalOrder]
    fills: list[OperationalFill]
    financing: str | None
    category_attribution: list[OperationalCategoryRow] | None


class EquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    captured_at: str
    equity: str
    realized_pnl_day: str


class EquitySeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    points: list[EquityPoint]


def _db_dir() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(os.environ.get("ALPHABRIEF_HOME", "~/.alphabrief")).expanduser()


def _db_path() -> Path:
    db_dir = _db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


def _account_id() -> str:
    return os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID", "not-configured")


def _open_paper_store() -> PaperStore:
    return PaperStore(db_path=_db_path())


def _open_catalog() -> InstrumentCatalogStore | None:
    try:
        return InstrumentCatalogStore(db_path=_db_path())
    except Exception:
        return None


def _open_recon() -> BrokerReconStore:
    return BrokerReconStore(db_path=_db_path())


def _positions(payload: Any) -> list[tuple[str, Decimal, Decimal]]:
    """(symbol, quantity, average_price) rows from a stored snapshot."""
    rows: list[tuple[str, Decimal, Decimal]] = []
    raw = payload or {}
    if not isinstance(raw, dict):
        return rows
    for symbol, value in raw.items():
        if not isinstance(value, dict):
            continue
        quantity = value.get("quantity", value.get("qty"))
        price = value.get("average_price", value.get("avg_price"))
        if quantity is None or price is None:
            continue
        try:
            rows.append(
                (
                    str(symbol),
                    Decimal(str(quantity)),
                    Decimal(str(price)),
                )
            )
        except Exception:
            continue
    return rows


@router.get("/portfolio", response_model=PortfolioOperationalResponse)
def operational_portfolio() -> PortfolioOperationalResponse:
    """Return the persisted portfolio resource from runtime stores."""
    store = _open_paper_store()
    try:
        snapshot = store.get_latest_portfolio_snapshot()
        audit = store.get_audit_events()
    finally:
        store.close()

    if snapshot is None:
        return PortfolioOperationalResponse(
            account_id=_account_id(),
            snapshot_id=None,
            observed_at=None,
            cash=None,
            nav=None,
            realized_pnl=None,
            unrealized_pnl=None,
            margin_used=None,
            exposure=None,
            positions=[],
            pending_orders=[],
            fills=[],
            financing=None,
            category_attribution=None,
        )

    cash = Decimal(str(snapshot["cash"]))
    total_value = Decimal(str(snapshot["total_value"]))
    realized = Decimal(str(snapshot["realized_pnl"]))
    unrealized = total_value - cash - realized

    positions = _positions(snapshot.get("positions"))
    gross = sum(
        (abs(quantity) * price for _, quantity, price in positions),
        Decimal("0"),
    )
    net = sum((quantity * price for _, quantity, price in positions), Decimal("0"))

    catalog = _open_catalog()
    margin_used: Decimal | None = None
    category_rows: list[OperationalCategoryRow] | None = None
    if catalog is not None:
        try:
            projection = catalog.current_projection()
        except Exception:
            projection = None
        catalog.close()
        if projection is not None:
            by_symbol = {
                instrument.name: instrument
                for instrument in projection.instruments
            }
            try:
                margin_used = sum(
                    (
                        abs(quantity)
                        * price
                        * by_symbol[symbol].margin_rate
                        for symbol, quantity, price in positions
                    ),
                    Decimal("0"),
                )
            except KeyError:
                margin_used = None
            categories: dict[str, list[Decimal]] = {}
            for symbol, quantity, price in positions:
                instrument = by_symbol.get(symbol)
                if instrument is None:
                    category_rows = None
                    break
                classified = classify_instrument(instrument)
                entry = categories.setdefault(
                    classified.category, [Decimal("0"), Decimal("0")]
                )
                notional = abs(quantity) * price
                entry[0] += notional
                entry[1] += quantity * price
            else:
                category_rows = [
                    OperationalCategoryRow(
                        category=category,
                        gross_exposure=str(values[0]),
                        net_exposure=str(values[1]),
                    )
                    for category, values in sorted(categories.items())
                ]

    recon = _open_recon()
    try:
        order_rows = recon.list_order_id_map()
    finally:
        recon.close()
    pending_orders = [
        OperationalOrder(
            client_order_id=str(row.get("client_order_id", "")),
            broker_order_id=str(row.get("broker_order_id", "")),
            status=str(row.get("status", "")),
        )
        for row in order_rows
        if str(row.get("status", "")).upper() not in {"FILLED", "CANCELLED", "REJECTED"}
    ]
    fills = [
        OperationalFill(
            event_id=str(entry["id"]),
            order_id=_detail_str(entry, "order_id"),
            message=_detail_str(entry, "message") or "",
            created_at=str(entry.get("created_at", "")),
        )
        for entry in audit
        if entry.get("event_type") == "order_filled"
        or _detail_str(entry, "fill_id") is not None
    ]

    return PortfolioOperationalResponse(
        account_id=_account_id(),
        snapshot_id=str(snapshot["id"]),
        observed_at=str(snapshot["created_at"]),
        cash=str(cash),
        nav=str(total_value),
        realized_pnl=str(realized),
        unrealized_pnl=str(unrealized),
        margin_used=str(margin_used) if margin_used is not None else None,
        exposure=OperationalExposure(
            gross_exposure=str(gross), net_exposure=str(net)
        ),
        positions=[
            OperationalPosition(
                symbol=symbol,
                quantity=str(quantity),
                average_price=str(price),
            )
            for symbol, quantity, price in positions
        ],
        pending_orders=pending_orders,
        fills=fills,
        financing=None,
        category_attribution=category_rows,
    )


@router.get("/equity", response_model=EquitySeriesResponse)
def operational_equity(limit: int = 100) -> EquitySeriesResponse:
    """Return the persisted account equity series (newest first)."""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be in [1, 1000]")
    store = _open_paper_store()
    try:
        rows = store._conn.execute(
            """SELECT snapshot_id, captured_at, equity, realized_pnl_day
               FROM account_equity_snapshots
               ORDER BY captured_at DESC
               LIMIT ?""",
            [limit],
        ).fetchall()
    finally:
        store.close()
    points = [
        EquityPoint(
            snapshot_id=str(row[0]),
            captured_at=str(row[1]),
            equity=str(row[2]),
            realized_pnl_day=str(row[3]),
        )
        for row in rows
    ]
    return EquitySeriesResponse(account_id=_account_id(), points=points)


def _detail_str(entry: dict[str, Any], key: str) -> str | None:
    details = entry.get("details", {})
    if not isinstance(details, dict):
        return None
    value = details.get(key)
    return str(value) if value is not None else None
