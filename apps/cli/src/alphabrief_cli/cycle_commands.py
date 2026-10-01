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
from alphabrief_api.db.model_call import ModelCallStore
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

#: Exposure caps as fractions of NAV (PROJECT_GUIDE 5.6).
MAX_ORDER_NOTIONAL_PCT = Decimal("0.50")
MAX_TOTAL_EXPOSURE_PCT = Decimal("1.50")


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


def _risk_gate(
    instruments: tuple[str, ...], *, nav: Decimal | None = None
) -> RiskGate:
    """The reviewed risk boundary for one cycle (PROJECT_GUIDE 5.6/5.7).

    ``nav`` selects the exposure-cap regime. With a live NAV (the
    risk-sized production path) the caps are the guide's fractions of NAV:
    50% of NAV per order and 150% of NAV of total notional. Without one
    (the S9 fixed-units pre-run) the reviewed absolute caps from
    ``config/paper_execution_policy.yaml`` apply instead.
    """
    from alphabrief_risk import KillSwitch, KillSwitchStore
    from alphabrief_risk.entry_rules import EntryRulePolicy

    policy = load_paper_execution_policy(load_settings().execution_policy_file)
    if nav is not None and nav > 0:
        max_order_value = nav * MAX_ORDER_NOTIONAL_PCT
        max_total_exposure = nav * MAX_TOTAL_EXPOSURE_PCT
    else:
        max_order_value = policy.max_order_notional
        max_total_exposure = policy.max_total_exposure
    switch_store = KillSwitchStore(db_path=_paths.db_path())
    try:
        kill_switch = KillSwitch.from_store(switch_store)
    finally:
        switch_store.close()
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset(instruments),
            max_order_value=max_order_value,
            max_total_exposure=max_total_exposure,
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


def _risk_sources(symbols: tuple[str, ...]) -> Any:
    """The live OANDA risk-data sources for one cycle."""
    from alphabrief_execution.broker.oanda.risk_sources import (
        OandaRiskContextSources,
    )
    from alphabrief_execution.broker.recon_store import BrokerReconStore

    return OandaRiskContextSources(
        build_oanda_paper_client(),
        symbols=symbols,
        recon_store=BrokerReconStore(db_path=_paths.db_path()),
    )


def _account_context_provider(
    sources: Any,
    *,
    trading_day: str,
    store: AiTradingStore,
) -> Any:
    """Fetch the broker-fresh account context for each risk evaluation.

    The daily intent counters come from the durable attempt history, so the
    daily caps are enforced against what this system actually opened today
    rather than against a process-local counter.
    """

    def _build(symbol: str) -> Any:
        total, per_symbol = store.count_daily_opens(trading_day=trading_day)
        return sources.account_exposure_context(
            daily_open_count=total,
            daily_symbol_open_count=per_symbol.get(symbol, 0),
        )

    return _build


def _nav(sources: Any) -> Decimal:
    """The live account NAV used for the 5.6 exposure caps."""
    context = sources.account_exposure_context()
    nav: Decimal = context.equity if context.equity is not None else context.cash
    if nav <= 0:
        _exit_error("the broker account reports no positive NAV")
    return nav


def _sizing_provider(sources: Any) -> Any:
    """Build the 5.6 sizing inputs (NAV, factor, precision) per symbol.

    Everything comes from the broker: NAV from the account summary, the
    quote-currency conversion factor from the pricing response, and the
    precision/minimum size from the instrument metadata. A missing piece
    means the entry is not sized and therefore not traded.
    """
    from alphabrief_execution.broker.runtime import get_broker_runtime

    adapter = get_broker_runtime().adapter

    def _build(symbol: str) -> Any:
        from alphabrief_trader.sizing import SizingInputs

        context = sources.account_exposure_context()
        nav = context.equity if context.equity is not None else context.cash
        factor = sources.home_conversion_factor(symbol)
        if factor is None:
            return None
        metadata = adapter.instrument_metadata(symbol)  # type: ignore[attr-defined]
        return SizingInputs(
            nav=nav,
            quote_to_home=factor,
            trade_units_precision=int(metadata.trade_units_precision),
            minimum_trade_size=metadata.minimum_trade_size,
            # The soak-day risk halving is wired when the 14-day run starts
            # (S10); until then the full 0.25% risk applies.
            soak_day=None,
        )

    return _build


def _call_recorder(store: Any) -> Any:
    """Adapt the call store's ``save_call`` to the gateway's sink contract."""

    def _record(record: Any) -> None:
        store.save_call(record)

    return _record


def _model_budget(store: Any) -> Any:
    """The durable daily model budget for one cycle (PROJECT_GUIDE 5.13).

    The limits come from ``config/alphabrief.yaml`` and the usage from the
    recorded model calls, so a restart cannot hand the system a fresh
    allowance.
    """
    from alphabrief_models.channels import load_model_settings
    from alphabrief_models.model_budget import ModelBudgetGuard

    settings = load_model_settings()
    return ModelBudgetGuard(store, policy=settings.budget_policy())


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
    # Created before the committee so every terminal model call is
    # persisted: the daily budget (5.13) and the daily report (5.12) both
    # count real recorded calls, never an in-memory counter.
    model_calls = ModelCallStore(db_path=_paths.db_path())
    try:
        loader = _snapshot_loader(market_store)
        missing = [name for name in symbols if loader(name) is None]
        if missing:
            _exit_error(
                f"no stored OANDA bars for {', '.join(missing)}; run "
                f"'alphabrief data sync-oanda' first"
            )
        sources = _risk_sources(symbols)
        # Risk-based sizing is the production path; --units keeps the S9
        # fixed-size pre-run and its reviewed absolute caps.
        nav = _nav(sources) if parsed_units is None else None
        cycle = DailyTradingCycle(
            committee=build_ai_trading_committee(
                # save_call returns the call id; the sink contract is
                # "record it", so the return value is discarded.
                record_sink=_call_recorder(model_calls),
            ),
            risk_gate=_risk_gate(symbols, nav=nav),
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
                sources,
                trading_day=datetime.now(UTC).date().isoformat(),
                store=store,
            ),
            # 5.6 sizing: NAV, home-currency factor and instrument
            # precision all come from the broker, so an entry is sized
            # from the real account rather than from the committee's
            # own fraction estimate.
            sizing_provider=_sizing_provider(sources),
            # 5.13 budget: the daily channel allowance is enforced against
            # the recorded calls, so an exhausted plan stops the round
            # instead of burning the remaining quota.
            model_budget=_model_budget(model_calls),
        )
        record = cycle.run(list(symbols))
    finally:
        model_calls.close()
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


def _close_through_the_cycle(
    *,
    instrument: str,
    position_units: Decimal,
    reference_price: Decimal,
    reason: str,
    trading: TradingMode,
) -> dict[str, Any]:
    """Close one position via decision → RiskGate → OANDA (PROJECT_GUIDE 5.5).

    The reduce-only intent is checked only against the kill switch and
    rule 3, its RiskDecision is persisted with the attempt, and the order
    carries the intent's deterministic client order ID.
    """
    store = AiTradingStore(db_path=_paths.db_path())
    try:
        sources = _risk_sources((instrument,))
        cycle = DailyTradingCycle(
            # The close path never runs the committee (no snapshot), so no
            # model call can happen here and no sink is needed.
            committee=build_ai_trading_committee(),
            risk_gate=_risk_gate((instrument,)),
            execution_backend=(
                _execution_backend(symbols=(instrument,))
                if trading == "on"
                else _DisabledBackend()
            ),
            store=store,
            snapshot_loader=lambda symbol: None,
            enabled=True,
            trading_mode="on",
            account_context_provider=_account_context_provider(
                sources,
                trading_day=datetime.now(UTC).date().isoformat(),
                store=store,
            ),
        )
        cycle_id = f"close_{instrument}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        attempt = cycle.close_position(
            symbol=instrument,
            position_units=position_units,
            reference_price=reference_price,
            cycle_id=cycle_id,
            reason=reason,
            submit=trading == "on",
        )
    finally:
        store.close()
    return {
        "instrument": instrument,
        "outcome": attempt.outcome,
        "approved": attempt.approved,
        "risk_decision_id": attempt.risk_decision_id,
        "intent_id": attempt.intent_id,
        "reason": attempt.reason,
        "closed": attempt.filled,
        "broker_order_id": attempt.broker_order_id,
        "client_order_id": attempt.client_order_id,
        "cycle_id": cycle_id,
    }


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

    positions = _open_positions()
    results: list[dict[str, Any]] = []
    for decision in due:
        position = positions.get(decision.instrument)
        if position is None or position[0] == 0:
            results.append(
                {
                    "instrument": decision.instrument,
                    "closed": False,
                    "detail": "no position",
                }
            )
            continue
        results.append(
            _close_through_the_cycle(
                instrument=decision.instrument,
                position_units=position[0],
                reference_price=position[1],
                reason=decision.reason,
                trading=trading,
            )
        )
    _dump({"due": [d.to_dict() for d in due], "closed": results}, pretty=pretty)


def _open_positions() -> dict[str, tuple[Decimal, Decimal]]:
    """Signed units and mid price per instrument with an open position."""
    from alphabrief_execution.broker.oanda.position_ops import PositionOpsClient

    client = build_oanda_paper_client()
    positions = PositionOpsClient(client).list_positions().positions
    open_units: dict[str, Decimal] = {}
    for position in positions:
        units = position.long_units - position.short_units
        if units != 0:
            open_units[position.instrument] = units
    if not open_units:
        return {}
    sources = _risk_sources(tuple(sorted(open_units)))
    priced: dict[str, tuple[Decimal, Decimal]] = {}
    for instrument, units in open_units.items():
        mark = sources.mid_price(instrument)
        if mark is None:
            continue
        priced[instrument] = (units, mark)
    return priced


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
    symbol = _require_instrument(instrument)
    if not oanda_is_configured():
        _exit_error(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )
    positions = _open_positions()
    position = positions.get(symbol)
    if position is None:
        _dump(
            {"instrument": symbol, "closed": False, "detail": "no open position"},
            pretty=pretty,
        )
        return
    units, mark = position
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
    result = _close_through_the_cycle(
        instrument=symbol,
        position_units=units,
        reference_price=mark,
        reason="operator close",
        trading=trading,
    )
    _dump(result, pretty=pretty)
