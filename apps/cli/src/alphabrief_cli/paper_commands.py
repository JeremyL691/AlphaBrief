"""CLI subcommands for the paper trading module."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import typer
from alphabrief_core import OrderIntent
from alphabrief_data import MarketDataLoadError, load_ohlcv_csv
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PaperBrokerError,
    PortfolioState,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_strategy.spec import StrategySpec

paper_app = typer.Typer(
    help="Run paper-trading sessions against the broker simulator."
)


def _exit_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


@paper_app.command("run")
def run_cmd(
    data: Path = typer.Option(
        ..., "--data", help="Path to OHLCV CSV file", exists=True
    ),
    spec: Path = typer.Option(
        ..., "--spec", help="Path to StrategySpec JSON file", exists=True
    ),
    price: str = typer.Option(
        "100", "--price", help="Reference price for the paper order"
    ),
) -> None:
    """Start a paper-trading session for a strategy."""
    try:
        reference_price = Decimal(price)
    except Exception:
        _exit_error(f"invalid price value: {price!r}")

    # Load strategy spec
    try:
        spec_text = spec.read_text(encoding="utf-8")
        spec_data = json.loads(spec_text)
        strategy_spec = StrategySpec.model_validate(spec_data)
    except FileNotFoundError:
        _exit_error(f"spec file not found: {spec}")
    except json.JSONDecodeError as exc:
        _exit_error(f"invalid JSON in spec file: {exc}")
    except Exception as exc:
        _exit_error(f"invalid strategy spec: {exc}")

    # Load CSV bars
    try:
        symbol = strategy_spec.universe.symbols[0]
        bars = load_ohlcv_csv(
            data,
            symbol=symbol,
            source="cli",
            data_version="1",
        )
    except MarketDataLoadError as exc:
        _exit_error(f"failed to load market data: {exc}")
    except Exception as exc:
        _exit_error(f"failed to load market data: {exc}")

    if not bars:
        _exit_error("no bars loaded from CSV file")

    # Create permissive RiskGate
    risk_gate = RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset({symbol}),
        ),
    )

    # Create PaperBroker
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )

    # Create a single buy OrderIntent
    intent = OrderIntent(
        intent_id=f"intent_{uuid4().hex}",
        source="manual",
        symbol=symbol,
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="paper trading run via CLI",
        created_at=datetime.now(UTC),
    )

    # Evaluate via RiskGate
    decision = risk_gate.evaluate(
        intent,
        estimated_price=reference_price,
        data_quality_passed=True,
    )

    if not decision.approved:
        _exit_error(f"risk gate rejected order: {decision.reason}")

    # Submit via PaperBroker
    try:
        result = broker.submit(
            intent, decision, reference_price=reference_price
        )
    except PaperBrokerError as exc:
        _exit_error(f"paper broker rejected order: {exc}")

    # Print results
    print(f"Symbol: {result.order.symbol}")
    print(f"Side: {result.order.side}")
    print(f"Quantity: {result.order.quantity}")
    print(f"Order ID: {result.order.order_id}")
    print(f"Fill Price: {result.fill.price}")
    print(f"Gross Value: {result.fill.gross_value}")
    print(f"Fee: {result.fill.fee}")
    print(f"Portfolio Cash: {result.portfolio.cash}")
    pos_qty = result.portfolio.position_quantity(symbol)
    print(f"Portfolio Position ({symbol}): {pos_qty}")
    print(f"Portfolio Realized PnL: {result.portfolio.realized_pnl}")


@paper_app.command("status")
def status_cmd() -> None:
    """Show the current paper portfolio status."""
    print("Paper portfolio status not yet persisted. Run 'paper run' first.")


__all__ = ["paper_app"]
