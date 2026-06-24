"""Tests for the execution-side account-exposure projection (Phase 19 R19.2).

Drives the async adapter variant with a tiny in-memory fake adapter and
the sync variant with a legacy :class:`PortfolioState`. Verifies the
projection sums gross notional (``abs(qty) * mark``), honors explicit
``mark_prices``, and carries the account snapshot's cash / account_id /
captured_at through to the risk-layer value object.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alphabrief_execution.broker.exposure import (
    build_account_exposure_context,
    build_account_exposure_context_from_portfolio,
)
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderStatus,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.portfolio import PortfolioState
from alphabrief_execution.portfolio import Position as PortfolioPosition

CAPTURED = datetime(2026, 6, 23, 10, 0, tzinfo=UTC)


class _FakeAdapter(BrokerAdapter):
    """Minimal adapter: only get_positions / get_account are exercised."""

    def __init__(
        self,
        *,
        positions: list[Position],
        account: AccountSnapshot,
    ) -> None:
        self._positions = positions
        self._account = account

    async def health(self) -> BrokerHealth:
        return BrokerHealth(healthy=True, detail="ok", checked_at=CAPTURED)

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:  # pragma: no cover - not used by the projection
        raise NotImplementedError

    async def cancel(self, broker_order_id: str) -> CancelResult:  # pragma: no cover
        raise NotImplementedError

    async def get_order(self, broker_order_id: str) -> OrderState:  # pragma: no cover
        raise NotImplementedError

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:  # pragma: no cover
        return []

    async def list_fills(
        self, since: datetime | None = None
    ) -> list[Fill]:  # pragma: no cover
        return []

    async def get_positions(self) -> list[Position]:
        return list(self._positions)

    async def get_account(self) -> AccountSnapshot:
        return self._account


def _account(
    *,
    cash: Decimal = Decimal("1000"),
    account_id: str = "acct-fake",
) -> AccountSnapshot:
    return AccountSnapshot(
        account_id=account_id,
        cash=cash,
        equity=Decimal("1000"),
        buying_power=Decimal("2000"),
        currency="USD",
        captured_at=CAPTURED,
    )


def _pos(symbol: str, qty: Decimal, avg: Decimal) -> Position:
    return Position(symbol=symbol, quantity=qty, average_price=avg)


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Async adapter variant
# ---------------------------------------------------------------------------


def test_async_projection_sums_exposure_from_average_price() -> None:
    adapter = _FakeAdapter(
        positions=[
            _pos("SPY", Decimal("2"), Decimal("100")),
            _pos("QQQ", Decimal("1"), Decimal("50")),
        ],
        account=_account(cash=Decimal("750")),
    )
    ctx = _run(build_account_exposure_context(adapter))
    # 2*100 + 1*50 = 250
    assert ctx.current_total_exposure == Decimal("250")
    assert ctx.exposure_by_symbol == {
        "SPY": Decimal("200"),
        "QQQ": Decimal("50"),
    }
    assert ctx.cash == Decimal("750")
    assert ctx.account_id == "acct-fake"
    assert ctx.captured_at == CAPTURED


def test_async_projection_empty_positions_is_zero_exposure() -> None:
    adapter = _FakeAdapter(positions=[], account=_account())
    ctx = _run(build_account_exposure_context(adapter))
    assert ctx.current_total_exposure == Decimal("0")
    assert ctx.exposure_by_symbol == {}


def test_async_projection_uses_mark_prices_when_supplied() -> None:
    adapter = _FakeAdapter(
        positions=[_pos("SPY", Decimal("2"), Decimal("100"))],
        account=_account(),
    )
    ctx = _run(
        build_account_exposure_context(adapter, mark_prices={"SPY": Decimal("120")})
    )
    # mark 120 overrides average_price 100 -> 2*120 = 240
    assert ctx.current_total_exposure == Decimal("240")


def test_async_projection_marks_abs_quantity_for_shorts() -> None:
    adapter = _FakeAdapter(
        positions=[_pos("SPY", Decimal("-3"), Decimal("100"))],
        account=_account(),
    )
    ctx = _run(build_account_exposure_context(adapter))
    # abs(-3) * 100 = 300
    assert ctx.current_total_exposure == Decimal("300")


def test_async_projection_skips_zero_quantity_positions() -> None:
    adapter = _FakeAdapter(
        positions=[_pos("SPY", Decimal("0"), Decimal("100"))],
        account=_account(),
    )
    ctx = _run(build_account_exposure_context(adapter))
    assert ctx.current_total_exposure == Decimal("0")
    assert ctx.exposure_by_symbol == {}


# ---------------------------------------------------------------------------
# Sync portfolio variant
# ---------------------------------------------------------------------------


def test_sync_projection_from_portfolio_sums_exposure() -> None:
    portfolio = PortfolioState(
        cash=Decimal("900"),
        positions={
            "SPY": PortfolioPosition(
                symbol="SPY", quantity=Decimal("2"), average_price=Decimal("100")
            ),
            "QQQ": PortfolioPosition(
                symbol="QQQ", quantity=Decimal("1"), average_price=Decimal("50")
            ),
        },
    )
    ctx = build_account_exposure_context_from_portfolio(
        portfolio, clock=lambda: CAPTURED
    )
    assert ctx.current_total_exposure == Decimal("250")
    assert ctx.exposure_by_symbol == {
        "SPY": Decimal("200"),
        "QQQ": Decimal("50"),
    }
    assert ctx.cash == Decimal("900")
    assert ctx.account_id == "paper_local"
    assert ctx.captured_at == CAPTURED


def test_sync_projection_empty_portfolio_is_zero_exposure() -> None:
    portfolio = PortfolioState(cash=Decimal("100000"))
    ctx = build_account_exposure_context_from_portfolio(
        portfolio, clock=lambda: CAPTURED
    )
    assert ctx.current_total_exposure == Decimal("0")
    assert ctx.cash == Decimal("100000")


def test_sync_projection_accepts_mark_prices() -> None:
    portfolio = PortfolioState(
        cash=Decimal("900"),
        positions={
            "SPY": PortfolioPosition(
                symbol="SPY", quantity=Decimal("2"), average_price=Decimal("100")
            )
        },
    )
    ctx = build_account_exposure_context_from_portfolio(
        portfolio, mark_prices={"SPY": Decimal("120")}, clock=lambda: CAPTURED
    )
    assert ctx.current_total_exposure == Decimal("240")
