"""Execution-side projection of live broker state into a risk context.

This module is the **only** place that touches a :class:`BrokerAdapter`
in order to feed account-level state to
:class:`alphabrief_risk.RiskGate`. It projects broker positions and the
account snapshot into an :class:`AccountExposureContext` — a plain
data carrier owned by the risk layer — so the dependency arrow stays
one-way (execution -> risk) and :class:`RiskGate` never imports the
execution layer.

Two variants:

* :func:`build_account_exposure_context` — async, reads from an
  external :class:`BrokerAdapter` (the Alpaca paper path).
* :func:`build_account_exposure_context_from_portfolio` — sync, reads
  from the in-memory legacy :class:`PortfolioState` used by the API's
  paper route (no external adapter required).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_risk import AccountExposureContext

from alphabrief_execution.broker.port import BrokerAdapter
from alphabrief_execution.portfolio import PortfolioState


def _exposure_from_positions(
    positions: list[tuple[str, Decimal, Decimal]],
    *,
    mark_prices: dict[str, Decimal] | None,
) -> tuple[Decimal, dict[str, Decimal]]:
    """Sum gross notional across positions.

    ``positions`` is ``(symbol, quantity, average_price)`` tuples. Gross
    notional per position is ``abs(quantity) * mark_price`` where the
    mark is ``mark_prices[symbol]`` if supplied else ``average_price``.
    Returns ``(current_total_exposure, exposure_by_symbol)``.
    """
    total = Decimal("0")
    by_symbol: dict[str, Decimal] = {}
    for symbol, quantity, average_price in positions:
        if quantity == 0:
            continue
        mark = (
            mark_prices[symbol]
            if mark_prices is not None and symbol in mark_prices
            else average_price
        )
        # ponytail:mark_price_ceiling: when no live mark is supplied we
        # fall back to ``average_price``, so exposure is cost-basis not
        # current market. Ceiling: understates exposure in a rising
        # market and overstates it in a falling one. Upgrade path is to
        # pass ``mark_prices`` from a quote provider when one exists.
        notional = abs(quantity) * mark
        total += notional
        by_symbol[symbol] = by_symbol.get(symbol, Decimal("0")) + notional
    return total, by_symbol


async def build_account_exposure_context(
    adapter: BrokerAdapter,
    *,
    mark_prices: dict[str, Decimal] | None = None,
) -> AccountExposureContext:
    """Project a live broker adapter into an :class:`AccountExposureContext`.

    Calls ``adapter.get_positions()`` and ``adapter.get_account()``
    (both required by the :class:`BrokerAdapter` port) and sums gross
    notional across positions. See :func:`_exposure_from_positions`
    for the mark-price fallback.
    """
    positions = await adapter.get_positions()
    account = await adapter.get_account()
    total, by_symbol = _exposure_from_positions(
        [(p.symbol, p.quantity, p.average_price) for p in positions],
        mark_prices=mark_prices,
    )
    return AccountExposureContext(
        current_total_exposure=total,
        exposure_by_symbol=by_symbol,
        cash=account.cash,
        account_id=account.account_id,
        captured_at=account.captured_at,
    )


def build_account_exposure_context_from_portfolio(
    portfolio: PortfolioState,
    *,
    account_id: str = "paper_local",
    mark_prices: dict[str, Decimal] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AccountExposureContext:
    """Project an in-memory :class:`PortfolioState` into an
    :class:`AccountExposureContext`.

    Used by the API paper route, which runs the legacy
    :class:`PaperBroker` (no external adapter). The legacy
    :class:`PortfolioState` only holds non-negative quantities, so
    ``abs()`` is a no-op there but kept for parity with the adapter
    variant.
    """
    total, by_symbol = _exposure_from_positions(
        [(p.symbol, p.quantity, p.average_price) for p in portfolio.positions.values()],
        mark_prices=mark_prices,
    )
    return AccountExposureContext(
        current_total_exposure=total,
        exposure_by_symbol=by_symbol,
        cash=portfolio.cash,
        account_id=account_id,
        captured_at=clock(),
    )


__all__ = [
    "build_account_exposure_context",
    "build_account_exposure_context_from_portfolio",
]
