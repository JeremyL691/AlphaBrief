"""CLI subcommands for the paper trading module."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import typer
from alphabrief_api.db import PaperStore
from alphabrief_core import OrderIntent
from alphabrief_data import MarketDataLoadError, load_ohlcv_csv
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PaperBrokerError,
    PortfolioState,
)
from alphabrief_risk import RiskContextDecision, RiskGate, RiskLimitConfig
from alphabrief_strategy.spec import StrategySpec

from alphabrief_cli.api_client import is_api_running

paper_app = typer.Typer(
    help="Run paper-trading sessions against the broker simulator."
)


def _exit_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def _open_paper_store() -> PaperStore:
    """Return a store rooted at ``$ALPHABRIEF_DATA_DIR`` (if set)."""
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return PaperStore(db_path=db_dir / "alphabrief.db")
    return PaperStore()


def _parse_risk_context(
    raw: str | None, source_label: str
) -> RiskContextDecision | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _exit_error(f"invalid JSON in {source_label}: {exc}")
    if not isinstance(data, dict):
        _exit_error(f"{source_label} must be a JSON object")
    try:
        return RiskContextDecision.model_validate(data)
    except ValueError as exc:
        _exit_error(f"invalid RiskContextDecision in {source_label}: {exc}")
    return None


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
    risk_context: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--risk-context",
        help=(
            "Optional RiskContextDecision as inline JSON. Tightens the "
            "order (human review flag, position-size reduction) but "
            "never relaxes limits."
        ),
    ),
    risk_context_file: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--risk-context-file",
        help="Optional path to a JSON file with a RiskContextDecision.",
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

    if risk_context is not None and risk_context_file is not None:
        _exit_error(
            "--risk-context and --risk-context-file are mutually exclusive"
        )

    parsed_context: RiskContextDecision | None = None
    if risk_context is not None:
        parsed_context = _parse_risk_context(risk_context, "--risk-context")
    elif risk_context_file is not None:
        try:
            file_text = risk_context_file.read_text(encoding="utf-8")
        except OSError as exc:
            _exit_error(
                f"could not read risk context file {risk_context_file}: {exc}"
            )
        parsed_context = _parse_risk_context(
            file_text, f"--risk-context-file {risk_context_file}"
        )

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
        risk_context=parsed_context,
    )

    if not decision.approved:
        _exit_error(f"risk gate rejected order: {decision.reason}")

    if decision.requires_human_review:
        _exit_error(
            "risk decision requires human review; "
            "auto-execution blocked by PaperBroker"
        )

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
    if parsed_context is not None:
        print(f"Applied Risk Context: {parsed_context.decision_id}")


@paper_app.command("status")
def status_cmd() -> None:
    """Show the current paper portfolio status."""
    # ponytail: read from PaperStore when no API is running. The CLI
    # ``paper run`` path is in-memory only, so status will reflect
    # persistent snapshots produced by the API or scheduler paths.
    if is_api_running():
        print(
            "paper status via API: not yet wired; "
            "use GET /api/v1/paper/portfolio instead",
            file=sys.stderr,
        )
        sys.exit(1)

    store = _open_paper_store()
    try:
        snap = store.get_latest_portfolio_snapshot()
    finally:
        store.close()

    if snap is None:
        print("Paper portfolio status not yet persisted. Run 'paper run' first.")
        return

    print(f"snapshot_id: {snap.get('snapshot_id', '')}")
    print(f"captured_at: {snap.get('captured_at', '')}")
    print(f"Portfolio Cash: {snap.get('cash', '0')}")
    print(f"Realized PnL: {snap.get('realized_pnl', '0')}")
    positions = snap.get("positions") or []
    if positions:
        for pos in positions:
            sym = pos.get("symbol", "?")
            qty = pos.get("quantity", "?")
            avg = pos.get("average_price", "?")
            print(f"Position: {sym} qty={qty} avg_price={avg}")
    else:
        print("Positions: (none)")


__all__ = ["paper_app"]
