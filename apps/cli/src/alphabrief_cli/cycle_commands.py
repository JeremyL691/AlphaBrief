"""CLI commands for the trading cycle (PROJECT_GUIDE S3-4 / S3-5).

``alphabrief cycle run --once --instrument EUR_USD --units 1000 --trading on``
runs the full committee for one instrument and, when trading is on,
submits through the same decision → RiskGate → persisted RiskDecision →
OANDA chain as the unattended runtime. ``--units`` pins the first orders
to a fixed size as a safety measure; ``--force-direction`` is the
documented vertical-slice exception and requires ``--reason``.

``alphabrief cycle close --instrument EUR_USD`` submits a reduce-only
market order for the current position and reconciles immediately.

Nothing here bypasses risk: ``--trading off`` runs the whole cycle and
stops before submitting, recording ``NO_TRADE_TRADING_OFF``.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import typer
from alphabrief_api.db import AiTradingStore
from alphabrief_api.db.market_data import MarketDataStore
from alphabrief_core import (
    load_paper_execution_policy,
    load_settings,
)
from alphabrief_core import paths as _paths
from alphabrief_execution.broker.runtime import (
    build_oanda_paper_client,
    get_broker_runtime,
    oanda_is_configured,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    ExternalPaperExecutionBackend,
    MarketSnapshot,
    SnapshotLoader,
    build_ai_trading_committee,
)

cycle_app = typer.Typer(help="Run one trading cycle or close a position.")

TradingMode = Literal["on", "off"]

#: The reviewed trading universe; an instrument outside it is refused.
DEFAULT_UNIVERSE = ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD")


def _dump(payload: object, *, pretty: bool) -> None:
    json.dump(payload, sys.stdout, indent=2 if pretty else None, default=str)
    sys.stdout.write("\n")


def _exit_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def _snapshot_loader(market_store: MarketDataStore) -> SnapshotLoader:
    """Build snapshots from stored OANDA bars (no synthetic prices).

    The ATR(14) of the H1 series is computed from the same stored candles
    and attached to the snapshot: the stop distance depends on it, and a
    missing ATR means no protective order (never a guessed one).
    """
    from alphabrief_trader.stops import atr_from_bars

    def _loader(symbol: str) -> MarketSnapshot | None:
        bars = market_store.get_bar_models(symbol)
        if not bars:
            return None
        latest = bars[-1]
        h1 = [
            bar
            for bar in bars
            if bar.data_version.endswith(":H1")
        ]
        atr = atr_from_bars(
            [bar.high for bar in h1],
            [bar.low for bar in h1],
            [bar.close for bar in h1],
        )
        return MarketSnapshot(
            symbol=symbol,
            reference_price=latest.close,
            atr=atr,
            data_version=latest.data_version,
            captured_at=latest.timestamp,
        )

    return _loader


def _risk_gate(instruments: tuple[str, ...]) -> RiskGate:
    """The reviewed risk boundary for one cycle (PROJECT_GUIDE 5.6/5.7)."""
    from alphabrief_risk import KillSwitch, KillSwitchStore
    from alphabrief_risk.entry_rules import EntryRulePolicy

    policy = load_paper_execution_policy(load_settings().execution_policy_file)
    switch_store = KillSwitchStore(db_path=_paths.db_path())
    try:
        kill_switch = KillSwitch.from_store(switch_store)
    finally:
        switch_store.close()
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset(instruments),
            max_order_value=policy.max_order_notional,
            max_total_exposure=policy.max_total_exposure,
            entry_rules=EntryRulePolicy(
                # Rule 3: quotes must be fresh and tradeable.
                max_quote_age_seconds=15,
                require_quote_tradeable=True,
                # Rule 7: at most 5 opens a day, at most 1 per symbol.
                max_daily_opens=5,
                max_daily_symbol_opens=1,
                # Rule 8: at most 3 instruments at once.
                max_open_positions=3,
                # Rule 13: close-only from Friday 13:00 UTC and all weekend.
                block_weekend_and_late_friday=True,
                # Rule 14: an entry must carry usable protective orders.
                require_protective_orders=True,
            ),
        ),
        kill_switch=kill_switch,
    )


def _account_context_provider(
    symbols: tuple[str, ...],
    *,
    trading_day: str,
    store: AiTradingStore,
) -> Any:
    """Fetch the broker-fresh account context for each risk evaluation.

    The daily intent counters come from the durable attempt history, so the
    daily caps are enforced against what this system actually opened today
    rather than against a process-local counter.
    """
    from alphabrief_execution.broker.oanda.risk_sources import (
        OandaRiskContextSources,
    )
    from alphabrief_execution.broker.recon_store import BrokerReconStore

    sources = OandaRiskContextSources(
        build_oanda_paper_client(),
        symbols=symbols,
        recon_store=BrokerReconStore(db_path=_paths.db_path()),
    )

    def _build() -> Any:
        total, per_symbol = store.count_daily_opens(trading_day=trading_day)
        return sources.account_exposure_context(
            daily_open_count=total,
            daily_symbol_open_count=per_symbol.get(symbols[0], 0),
        )

    return _build


def _parse_units(raw: str | None) -> Decimal | None:
    """Parse the optional fixed order size as a Decimal."""
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except (ArithmeticError, ValueError) as exc:
        raise typer.BadParameter(f"--units must be a decimal number: {raw!r}") from exc
    if value <= 0:
        raise typer.BadParameter("--units must be positive")
    return value


def _require_instrument(instrument: str) -> str:
    normalized = instrument.strip().upper()
    if normalized not in DEFAULT_UNIVERSE:
        _exit_error(
            f"{normalized} is not in the reviewed trading universe "
            f"{sorted(DEFAULT_UNIVERSE)}"
        )
    return normalized


def _execution_backend(
    *, symbols: tuple[str, ...] = DEFAULT_UNIVERSE
) -> ExternalPaperExecutionBackend:
    if not oanda_is_configured():
        _exit_error(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )
    return ExternalPaperExecutionBackend(
        get_broker_runtime().adapter,
        risk_symbols=symbols,
    )


@cycle_app.command("run")
def run_cmd(
    once: bool = typer.Option(  # noqa: B008
        False,
        "--once",
        help="Run exactly one cycle and exit.",
    ),
    instrument: str | None = typer.Option(  # noqa: B008
        None,
        "--instrument",
        help=(
            "Instrument to trade (must be in the reviewed universe). "
            "Omit to run the whole reviewed universe."
        ),
    ),
    units: str | None = typer.Option(  # noqa: B008
        None,
        "--units",
        help=(
            "Fixed order size overriding position sizing (first-order "
            "safety measure, e.g. 1000)."
        ),
    ),
    trading: TradingMode = typer.Option(  # noqa: B008
        "off",
        "--trading",
        help="'off' runs the cycle and stops before submitting; 'on' submits.",
    ),
    force_direction: str | None = typer.Option(  # noqa: B008
        None,
        "--force-direction",
        help=(
            "Vertical-slice exception: 'long' or 'short'. The committee "
            "output is still recorded; requires --reason."
        ),
    ),
    reason: str | None = typer.Option(  # noqa: B008
        None,
        "--reason",
        help="Why the direction is forced (recorded in the intent).",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Run one trading cycle for a single instrument."""
    if not once:
        _exit_error(
            "only --once is supported here; use 'alphabrief run' for the daemon"
        )
    symbols = (
        (_require_instrument(instrument),)
        if instrument is not None
        else DEFAULT_UNIVERSE
    )
    symbol = symbols[0]
    parsed_units = _parse_units(units)
    if force_direction is not None:
        if force_direction not in {"long", "short"}:
            _exit_error("--force-direction must be 'long' or 'short'")
        if not (reason or "").strip():
            _exit_error("--force-direction requires --reason")

    store = AiTradingStore(db_path=_paths.db_path())
    market_store = MarketDataStore(db_path=_paths.db_path())
    try:
        loader = _snapshot_loader(market_store)
        missing = [name for name in symbols if loader(name) is None]
        if missing:
            _exit_error(
                f"no stored OANDA bars for {', '.join(missing)}; run "
                f"'alphabrief data sync-oanda' first"
            )
        cycle = DailyTradingCycle(
            committee=build_ai_trading_committee(),
            risk_gate=_risk_gate(symbols),
            execution_backend=(
                _execution_backend(symbols=(symbol,))
                if trading == "on"
                else _DisabledBackend()
            ),
            store=store,
            snapshot_loader=loader,
            enabled=True,
            quantity_override=parsed_units,
            direction_override=force_direction,
            override_reason=reason,
            trading_mode=trading,
            # The account context is read-only and is fetched in both
            # modes: with trading off the cycle still evaluates every rule
            # against the real account, it just stops before submitting.
            account_context_provider=_account_context_provider(
                symbols,
                trading_day=datetime.now(UTC).date().isoformat(),
                store=store,
            ),
        )
        record = cycle.run(list(symbols))
    finally:
        market_store.close()
        store.close()

    _dump(
        {
            "cycle_id": record.cycle_id,
            "instrument": symbol if len(symbols) == 1 else None,
            "symbols": list(symbols),
            "trading": trading,
            "outcome": record.outcome,
            "summary": record.summary,
            "plan_count": len(record.plans),
            "attempt_count": len(record.attempts),
            "attempts": [
                {
                    "intent_id": attempt.intent_id,
                    "risk_decision_id": attempt.risk_decision_id,
                    "approved": attempt.approved,
                    "outcome": attempt.outcome,
                    "order_id": attempt.order_id,
                    "broker_order_id": attempt.broker_order_id,
                    "filled": attempt.filled,
                }
                for attempt in record.attempts
            ],
            "votes": [
                {"role": vote.role, "view": vote.view, "confidence": vote.confidence}
                for vote in record.votes
            ],
        },
        pretty=pretty,
    )


class _DisabledBackend:
    """Execution backend that refuses to submit (``--trading off``)."""

    def estimate_quantity(
        self, intent: Any, *, reference_price: Decimal
    ) -> Decimal | None:
        quantity = getattr(intent, "quantity", None)
        if isinstance(quantity, Decimal):
            return quantity
        return None

    def submit(
        self,
        intent: Any,
        decision: Any,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> Any:
        from alphabrief_trader.execution_backend import ExecutionBackendError

        raise ExecutionBackendError(
            "NO_TRADE_TRADING_OFF: trading is off; nothing was submitted"
        )


@cycle_app.command("close-due")
def close_due_cmd(
    trading: TradingMode = typer.Option(  # noqa: B008
        "on",
        "--trading",
        help="'on' submits the reduce-only orders; 'off' only reports.",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Close every position the policy says must close now (5.10).

    Two time-based triggers: the weekend close-out (Friday 19:00 UTC
    onward) and the maximum holding time. Protective orders filling at the
    broker are handled by the broker itself.
    """
    if not oanda_is_configured():
        _exit_error(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )
    from alphabrief_execution.broker.oanda.trade_ops import TradeOpsClient
    from alphabrief_trader.close_policy import positions_due_for_close

    client = build_oanda_paper_client()
    trades = TradeOpsClient(client).list_trades().trades
    # Only open trades can be closed; the broker also reports closed ones.
    open_trades = [trade for trade in trades if str(trade.state) == "OPEN"]
    decisions = positions_due_for_close(
        [(trade.instrument, trade.open_time) for trade in open_trades],
        now=datetime.now(UTC),
    )
    due = [decision for decision in decisions if decision.should_close]
    if not due:
        _dump(
            {
                "due": [],
                "detail": "no position is due for close",
                "checked": len(decisions),
            },
            pretty=pretty,
        )
        return
    if trading == "off":
        _dump(
            {
                "due": [decision.to_dict() for decision in due],
                "closed": [],
                "detail": "NO_TRADE_TRADING_OFF: trading is off",
            },
            pretty=pretty,
        )
        return

    results: list[dict[str, Any]] = []
    for decision in due:
        results.append(_close_instrument(decision.instrument, decision.reason))
    _dump({"due": [d.to_dict() for d in due], "closed": results}, pretty=pretty)


def _close_instrument(instrument: str, reason: str) -> dict[str, Any]:
    """Submit one reduce-only market order and report the outcome."""
    from alphabrief_execution.broker.oanda.order_ops import (
        OrderOperationError,
        OrderOpsClient,
    )
    from alphabrief_execution.broker.oanda.orders import OandaOrderRequest
    from alphabrief_execution.broker.oanda.position_ops import PositionOpsClient
    from alphabrief_execution.broker.runtime import get_broker_runtime

    client = build_oanda_paper_client()
    positions = PositionOpsClient(client).list_positions().positions
    position = next((p for p in positions if p.instrument == instrument), None)
    if position is None or (position.long_units == 0 and position.short_units == 0):
        return {"instrument": instrument, "closed": False, "detail": "no position"}
    units = position.long_units - position.short_units
    adapter = get_broker_runtime().adapter
    metadata = adapter.instrument_metadata(instrument)  # type: ignore[attr-defined]
    cycle_id = f"close_due_{instrument}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    try:
        created = OrderOpsClient(client).create_order(
            OandaOrderRequest(
                type="MARKET",
                instrument=instrument,
                units=-units,
                time_in_force="FOK",
                position_fill="DEFAULT",
            ),
            metadata,
            client_order_id=f"{cycle_id}:{instrument}",
            tag="alphabrief",
            comment=cycle_id,
        )
    except OrderOperationError as exc:
        return {"instrument": instrument, "closed": False, "detail": str(exc)}
    return {
        "instrument": instrument,
        "closed": True,
        "reason": reason,
        "broker_order_id": created.broker_order_id,
        "state": created.state,
        "cycle_id": cycle_id,
    }


@cycle_app.command("close")
def close_cmd(
    instrument: str = typer.Option(  # noqa: B008
        ...,
        "--instrument",
        help="Instrument whose position should be closed.",
    ),
    trading: TradingMode = typer.Option(  # noqa: B008
        "on",
        "--trading",
        help="'on' submits the reduce-only order; 'off' only reports.",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Close the current position with a reduce-only market order."""
    symbols = (
        (_require_instrument(instrument),)
        if instrument is not None
        else DEFAULT_UNIVERSE
    )
    symbol = symbols[0]
    if not oanda_is_configured():
        _exit_error(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )
    client = build_oanda_paper_client()
    from alphabrief_execution.broker.oanda.position_ops import PositionOpsClient

    positions = PositionOpsClient(client).list_positions().positions
    position = next((p for p in positions if p.instrument == symbol), None)
    if position is None or (position.long_units == 0 and position.short_units == 0):
        _dump(
            {"instrument": symbol, "closed": False, "detail": "no open position"},
            pretty=pretty,
        )
        return
    units = position.long_units - position.short_units
    if trading == "off":
        _dump(
            {
                "instrument": symbol,
                "closed": False,
                "detail": "NO_TRADE_TRADING_OFF: trading is off",
                "units": str(abs(units)),
            },
            pretty=pretty,
        )
        return

    from alphabrief_execution.broker.oanda.order_ops import (
        OrderOperationError,
        OrderOpsClient,
    )
    from alphabrief_execution.broker.oanda.orders import OandaOrderRequest
    from alphabrief_execution.broker.runtime import get_broker_runtime

    adapter = get_broker_runtime().adapter
    metadata = adapter.instrument_metadata(symbol)  # type: ignore[attr-defined]
    cycle_id = f"close_{symbol}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    try:
        created = OrderOpsClient(client).create_order(
            OandaOrderRequest(
                type="MARKET",
                instrument=symbol,
                units=-units,
                time_in_force="FOK",
                position_fill="DEFAULT",
            ),
            metadata,
            client_order_id=f"{cycle_id}:{symbol}",
            tag="alphabrief",
            comment=cycle_id,
        )
    except OrderOperationError as exc:
        _exit_error(f"close rejected: {exc}")
    _dump(
        {
            "instrument": symbol,
            "closed": True,
            "broker_order_id": created.broker_order_id,
            "state": created.state,
            "cycle_id": cycle_id,
        },
        pretty=pretty,
    )
