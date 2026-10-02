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
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import typer
from alphabrief_api.db import AiTradingStore, NewsStore
from alphabrief_api.db.market_data import MarketDataStore
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_core import (
    RiskDecision,
    load_paper_execution_policy,
    load_settings,
)
from alphabrief_core import paths as _paths
from alphabrief_execution.broker.oanda.input_facts import BrokerInputFacts
from alphabrief_execution.broker.oanda.market_sync import (
    SignalCandleObservation,
    observe_signal_candles,
)
from alphabrief_execution.broker.runtime import (
    build_oanda_paper_client,
    get_broker_runtime,
    oanda_is_configured,
)
from alphabrief_news.ingestion import NewsIngestionStore
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_risk.decision_binding import DecisionBindingService
from alphabrief_trader import (
    DailyTradingCycle,
    ExternalPaperExecutionBackend,
    MarketSnapshot,
    SnapshotLoader,
    StoredMarketSnapshotBuilder,
    build_ai_trading_committee,
)
from alphabrief_trader.schemas import NewsInputEvidence, SignalInputEvidence
from alphabrief_trader.shadow_store import ShadowStore

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


def _snapshot_loader(
    market_store: MarketDataStore,
    news_store: NewsStore,
    news_health: NewsIngestionStore,
    signal_observation: SignalCandleObservation | None = None,
    refresh_errors: dict[str, str] | None = None,
) -> SnapshotLoader:
    """Build snapshots from stored OANDA bars (no synthetic prices).

    The ATR(14) of the H1 series is computed from the same stored candles
    and attached to the snapshot: the stop distance depends on it, and a
    missing ATR means no protective order (never a guessed one).
    """
    from alphabrief_execution.broker.oanda.market_sync import BAR_SOURCE, TIMEFRAMES
    from alphabrief_trader.market_inputs import build_market_inputs
    from alphabrief_trader.signal_inputs import build_signal_inputs

    def _loader(symbol: str) -> MarketSnapshot | None:
        now = datetime.now(UTC)
        inputs = build_market_inputs(
            {
                tf: market_store.get_bar_models(
                    symbol, data_version_suffix=f":M:{tf}", source=BAR_SOURCE
                )
                for tf, _ in TIMEFRAMES
            },
            symbol=symbol,
            now=now,
        )
        bars = [bar for series in inputs.series.values() for bar in series]
        if not bars:
            return None
        h1 = inputs.series["H1"]
        latest = h1[-1] if h1 else max(bars, key=lambda bar: bar.timestamp)
        headlines = news_store.list_headlines(
            symbol=symbol, start=now - timedelta(hours=24), end=now, limit=20
        )
        # Freeze the exact inputs once: evidence and prompt must describe the
        # same bounded batch, not independent database reads with different clocks.
        builder = StoredMarketSnapshotBuilder(
            bar_loader=lambda requested: (
                h1 or sorted(bars, key=lambda bar: bar.timestamp)
            ),
            headline_loader=lambda requested, start, end, limit: headlines,
            max_headlines=20,
            clock=lambda: now,
        )
        snapshot = builder.build(symbol, reference_price_override=latest.close)
        if snapshot is None:
            return None
        return snapshot.model_copy(
            update={
                "atr": inputs.atr,
                "momentum_20d_pct": inputs.return_20d_pct,
                "volatility_20d_pct": inputs.volatility_20d_pct,
                "market_evidence": inputs.evidence.model_copy(
                    update={
                        "refresh_errors": {
                            key.split(":", 1)[1]: error
                            for key, error in (refresh_errors or {}).items()
                            if key.startswith(f"{symbol}:")
                        },
                    }
                ),
                "signal_evidence": (
                    SignalInputEvidence(
                        observed_at=now, errors={"inputs": "not_observed"}
                    )
                    if signal_observation is None
                    else build_signal_inputs(
                        signal_observation, daily=inputs.series["D"], now=now
                    )
                ),
                # Freshness is the broker candle time, never the builder's wall clock.
                "captured_at": inputs.evidence.latest_h1_end or latest.timestamp,
                "news_evidence": NewsInputEvidence(
                    family_fetched_at=news_health.successful_source_family_times(
                        now=now
                    ),
                    related_published_at={
                        h.headline_id: h.published_at for h in snapshot.news_items
                    },
                ),
            }
        )

    return _loader


def _signal_observation(market: MarketDataStore) -> SignalCandleObservation:
    """Read signals once per round through the same practice-only client."""
    return observe_signal_candles(build_oanda_paper_client(), store=market)


def _refresh_market_bars(
    market: MarketDataStore,
    symbols: tuple[str, ...],
) -> dict[str, str]:
    """Require an actual complete practice response for every FX window."""
    from alphabrief_execution.broker.oanda.market_sync import sync_bars

    _, errors = sync_bars(
        build_oanda_paper_client(),
        instruments=symbols,
        store=market,
        require_full_window=True,
    )
    return errors


def _risk_gate(
    instruments: tuple[str, ...],
    *,
    nav: Decimal | None = None,
    require_nav: bool = False,
) -> RiskGate:
    """The reviewed risk boundary for one cycle (PROJECT_GUIDE 5.6/5.7).

    ``nav`` selects the exposure-cap regime. With a live NAV (the
    risk-sized production path) the caps are the guide's fractions of NAV:
    50% of current NAV per order and 150% of current NAV of total notional,
    recomputed from each gate account context. Without one
    (the S9 fixed-units pre-run) the reviewed absolute caps from
    ``config/paper_execution_policy.yaml`` apply instead.
    """
    from alphabrief_risk import KillSwitch, KillSwitchStore
    from alphabrief_risk.entry_rules import EntryRulePolicy

    policy = load_paper_execution_policy(load_settings().execution_policy_file)
    max_order_value: Decimal | None
    max_total_exposure: Decimal | None
    if nav is not None and nav > 0:
        max_order_value = None
        max_total_exposure = None
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
            trading_enabled=not require_nav or (nav is not None and nav > 0),
            symbol_allowlist=frozenset(instruments),
            require_home_currency_exposure=True,
            max_order_value_pct=(
                MAX_ORDER_NOTIONAL_PCT if nav is not None and nav > 0 else None
            ),
            max_total_exposure_pct=(
                MAX_TOTAL_EXPOSURE_PCT if nav is not None and nav > 0 else None
            ),
            max_order_value=max_order_value,
            max_total_exposure=max_total_exposure,
            max_margin_utilization_pct=Decimal("0.30"),
            margin_warning_pct=Decimal("0.20"),
            max_daily_loss_pct=Decimal("0.01"),
            entry_rules=EntryRulePolicy(
                # Rule 3: quotes must be fresh and tradeable.
                max_quote_age_seconds=15,
                require_quote_tradeable=True,
                # Rule 7: at most 5 opens a day, at most 1 per symbol.
                max_daily_opens=5,
                max_daily_symbol_opens=1,
                # Rule 8: at most 3 instruments at once.
                max_open_positions=3,
                # Rule 6: no new exposure within 30 minutes of a
                # high-impact macro/news event for the instrument.
                event_window_minutes=30,
                # Rule 11: the soak drawdown state machine (3% blocks
                # 48h, 5% halts the soak) blocks new exposure.
                block_on_drawdown=True,
                # Rule 4: the spread must stay within 2x the median of the
                # same-period samples (5 samples minimum).
                max_spread_median_multiplier=Decimal("2"),
                min_spread_samples=5,
                require_loss_streak=True,
                # Rule 1 (freeze part) and rule 2 (CURRENCY classification).
                require_unfrozen=True,
                require_currency_type=True,
                # Rule 13: close-only from Friday 13:00 UTC and all weekend.
                block_weekend_and_late_friday=True,
                # Rule 14: an entry must carry usable protective orders.
                require_protective_orders=True,
            ),
        ),
        kill_switch=kill_switch,
    )


def _risk_sources(symbols: tuple[str, ...], *, recon_store: Any | None = None) -> Any:
    """The live OANDA risk-data sources for one cycle."""
    from alphabrief_execution.broker.oanda.risk_sources import (
        OandaRiskContextSources,
    )
    from alphabrief_execution.broker.recon_store import BrokerReconStore

    return OandaRiskContextSources(
        build_oanda_paper_client(),
        symbols=symbols,
        recon_store=(
            recon_store
            if recon_store is not None
            else BrokerReconStore(db_path=_paths.db_path())
        ),
    )


def _account_context_provider(
    sources: Any,
    *,
    trading_day: str,
    store: AiTradingStore,
    news_store: Any | None = None,
    universe: tuple[str, ...] = (),
    loss_store: Any | None = None,
) -> Any:
    """Fetch the broker-fresh account context for each risk evaluation.

    The daily intent counters come from the durable attempt history, so the
    daily caps are enforced against what this system actually opened today
    rather than against a process-local counter. The rule-6 event window is
    resolved from the stored headlines (real news, currency-tagged).
    """

    def _build(symbol: str) -> Any:
        total, per_symbol = store.count_daily_opens(trading_day=trading_day)
        events = _high_impact_event_map(news_store) if news_store is not None else {}
        verdict = _drawdown_verdict(sources)
        current_spread, recent_spreads = _spread_facts(sources, symbol)
        context = sources.account_exposure_context(
            symbol=symbol,
            symbol_types=_instrument_types(universe),
            daily_open_count=total,
            daily_symbol_open_count=per_symbol.get(symbol, 0),
            recent_high_impact_events=events,
            drawdown_block_reason=verdict.reason if verdict.blocked else None,
            current_spread=current_spread,
            recent_spreads=recent_spreads,
            include_daily_loss=True,
            include_loss_streak=True,
        )
        checked_at = datetime.now(UTC)
        stamp = context.daily_loss_captured_at
        daily_fresh = (
            stamp is not None
            and stamp.tzinfo is not None
            and stamp.astimezone(UTC).date() == checked_at.date()
            and 0 <= (checked_at - stamp).total_seconds() <= 60
        )
        context = context.model_copy(update={"daily_loss_blocked": None})
        if (
            loss_store is not None
            and daily_fresh
            and context.daily_loss_error is None
            and context.day_realized_pnl is not None
            and context.day_unrealized_pnl is not None
            and context.equity is not None
        ):
            try:
                blocked = loss_store.observe_daily_loss(
                    context.account_id,
                    observed_at=stamp,
                    realized_pnl=context.day_realized_pnl,
                    unrealized_pnl=context.day_unrealized_pnl,
                    nav=context.equity,
                    ceiling_pct=Decimal("0.01"),
                )
                context = context.model_copy(update={"daily_loss_blocked": blocked})
            except Exception:
                context = context.model_copy(
                    update={"daily_loss_error": "loss_state_unavailable"}
                )
        streak_stamp = context.loss_streak_captured_at
        if (
            loss_store is not None
            and context.closed_trade_results is not None
            and context.loss_streak_error is None
            and context.loss_streak_last_transaction_id is not None
            and streak_stamp is not None
            and streak_stamp.tzinfo is not None
            and 0 <= (checked_at - streak_stamp).total_seconds() <= 60
        ):
            try:
                states = loss_store.observe_closed_trades(
                    context.account_id,
                    trades=context.closed_trade_results,
                    observed_at=streak_stamp,
                    last_transaction_id=context.loss_streak_last_transaction_id,
                )
                frozen = dict(context.frozen_symbols)
                evidence: dict[str, dict[str, str]] = {}
                for instrument in set(universe) | set(states) | {symbol}:
                    state = states.get(instrument)
                    deadline = None if state is None else state.frozen_until
                    blocked = deadline is not None and checked_at < deadline
                    if blocked and deadline is not None:
                        frozen[instrument] = (
                            "three losing closed trades; frozen until "
                            + deadline.isoformat()
                        )
                    evidence[instrument] = {
                        "consecutive_losses": str(
                            0 if state is None else state.consecutive_losses
                        ),
                        "frozen_until": str(deadline),
                        "blocked": str(blocked).lower(),
                        "last_trade_id": str(
                            None if state is None else state.last_trade_id
                        ),
                        "last_close_transaction_id": str(
                            None if state is None else state.last_close_transaction_id
                        ),
                    }
                context = context.model_copy(
                    update={
                        "loss_streak_complete": True,
                        "frozen_symbols": frozen,
                        "loss_streak_evidence": evidence,
                    }
                )
            except Exception:
                context = context.model_copy(
                    update={
                        "loss_streak_complete": False,
                        "loss_streak_error": "loss_state_unavailable",
                    }
                )
        else:
            context = context.model_copy(update={"loss_streak_complete": False})
        return context

    return _build


def _instrument_types(symbols: tuple[str, ...]) -> dict[str, str]:
    """The broker's instrument classification per symbol (rule 2).

    Read from the account's own instrument catalog; a symbol the broker
    does not classify is left out, which the rule treats as fail-closed.
    """
    adapter = get_broker_runtime().adapter
    types: dict[str, str] = {}
    for symbol in symbols:
        try:
            metadata = adapter.instrument_metadata(symbol)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - an unclassified symbol stays unknown
            continue
        raw_type = getattr(metadata, "raw_type", None)
        if isinstance(raw_type, str) and raw_type:
            types[symbol] = raw_type
    return types


def _spread_facts(
    sources: Any, symbol: str
) -> tuple[Decimal | None, tuple[Decimal, ...]]:
    """Sample the live spread and read the same-hour history for rule 4.

    Every evaluation appends the current quote to the durable sample store
    (idempotent per timestamp), so the median the rule compares against is
    built from real observations. A missing quote yields no spread, which
    the rule treats as fail-closed.
    """
    from alphabrief_data.quote_samples import (
        SPREAD_MEDIAN_SAMPLE_LIMIT,
        QuoteSample,
        QuoteSampleStore,
    )

    quote = sources.live_quote(symbol)
    if quote is None:
        return None, ()
    bid, ask = quote
    now = datetime.now(UTC)
    store = QuoteSampleStore(db_path=_paths.db_path())
    try:
        store.record(
            QuoteSample(
                symbol=symbol,
                captured_at=now,
                bid=bid,
                ask=ask,
                spread=ask - bid,
                mid=(bid + ask) / Decimal(2),
            )
        )
        history = tuple(
            store.recent_spreads(
                symbol,
                hour=now.hour,
                limit=SPREAD_MEDIAN_SAMPLE_LIMIT,
            )
        )
    finally:
        store.close()
    return ask - bid, history


def _drawdown_verdict(sources: Any) -> Any:
    """Advance the persisted rule-11 state from the broker's real NAV.

    The high-water mark and the state live in DuckDB, so a restart cannot
    reset a drawdown block. The account id is used only as the state key.
    """
    from alphabrief_execution.broker.oanda.config import read_oanda_credentials
    from alphabrief_risk import DrawdownStateStore, evaluate_drawdown

    context = sources.account_exposure_context()
    nav = context.equity if context.equity is not None else context.cash
    try:
        _, account_id = read_oanda_credentials()
    except Exception:  # noqa: BLE001 - no credentials means no state key
        account_id = "unknown"
    store = DrawdownStateStore(db_path=_paths.db_path())
    try:
        previous = store.load(account_id)
        high_water = previous.high_water if previous and previous.high_water else nav
        verdict = evaluate_drawdown(
            equity=nav, high_water=high_water, now=datetime.now(UTC), previous=previous
        )
        store.save(account_id, verdict.state)
    finally:
        store.close()
    return verdict


def _high_impact_event_map(news_store: Any) -> dict[str, str]:
    """The ``symbol -> reason`` map of high-impact events inside the window.

    Headlines come from the durable news store (the same rows the
    scheduler ingested); the news layer does the classification, the risk
    rule only reads the map.
    """
    from datetime import timedelta

    from alphabrief_news.high_impact import HeadlineLike, high_impact_events
    from alphabrief_risk.event_window import window_reason_map

    now = datetime.now(UTC)
    window_minutes = 30
    try:
        headlines = news_store.list_headlines(
            start=now - timedelta(minutes=window_minutes),
            end=now + timedelta(minutes=1),
            limit=200,
        )
    except Exception as exc:  # noqa: BLE001 - unknown news must stop an entry
        raise RuntimeError("news impact evidence unavailable") from exc
    events = high_impact_events(
        [
            HeadlineLike(
                headline_id=headline.headline_id,
                title=headline.title,
                summary=headline.summary,
                source=headline.source,
                published_at=headline.published_at,
                symbols=tuple(headline.symbols),
            )
            for headline in headlines
        ],
        now=now,
        window_minutes=window_minutes,
    )
    return window_reason_map(events, now=now, window_minutes=window_minutes)


def _nav(sources: Any) -> Decimal | None:
    """The live account NAV used for the 5.6 exposure caps."""
    try:
        context = sources.account_exposure_context()
    except Exception:  # noqa: BLE001 - missing NAV disables entries, facts explain why
        return None
    nav: Decimal = context.equity if context.equity is not None else context.cash
    if nav <= 0:
        return None
    return nav


def _snapshot_refresher(
    sources: Any,
    store: AiTradingStore,
) -> Callable[[MarketSnapshot], MarketSnapshot]:
    """Observe broker inputs at each model/submit boundary; never fill missing facts."""

    def refresh(snapshot: MarketSnapshot) -> MarketSnapshot:
        try:
            facts: BrokerInputFacts = sources.decision_input_facts(snapshot.symbol)
        except Exception as exc:  # noqa: BLE001 - safe refusal rather than zero facts
            facts = BrokerInputFacts(
                symbol=snapshot.symbol, errors={"inputs": type(exc).__name__}
            )
        try:
            count, _ = store.count_daily_opens(
                trading_day=datetime.now(UTC).date().isoformat()
            )
            facts = facts.model_copy(update={"daily_open_count": count})
        except Exception as exc:  # noqa: BLE001 - an unknown counter is not zero
            facts = facts.model_copy(
                update={
                    "daily_open_count": None,
                    "errors": {**facts.errors, "daily_opens": type(exc).__name__},
                }
            )
        return snapshot.model_copy(update={"broker_evidence": facts})

    return refresh


def _sizing_provider(sources: Any) -> Any:
    """Build the 5.6 sizing inputs (NAV, factor, precision) per symbol.

    Everything comes from the broker: NAV from the account summary, the
    quote-currency conversion factor from the pricing response, and the
    precision/minimum size from the instrument metadata. A missing piece
    means the entry is not sized and therefore not traded.
    """
    adapter = get_broker_runtime().adapter

    def _build(symbol: str) -> Any:
        from alphabrief_trader.sizing import SizingInputs

        context = sources.account_exposure_context()
        nav = context.equity if context.equity is not None else context.cash
        factor = sources.home_conversion_factor(symbol)
        position_factor = context.quote_position_to_home.get(symbol)
        if factor is None or position_factor is None:
            return None
        metadata = adapter.instrument_metadata(symbol)  # type: ignore[attr-defined]
        # Rule 11: after a 3% drawdown block expires the system resumes at
        # half risk until the drawdown recovers.
        verdict = _drawdown_verdict(sources)
        multiplier = verdict.risk_multiplier
        if multiplier <= 0:
            # A blocked state never reaches sizing (the gate rejects the
            # entry first); sizing itself always uses a positive risk.
            multiplier = Decimal("1")
        return SizingInputs(
            nav=nav,
            quote_to_home=factor,
            quote_position_to_home=position_factor,
            trade_units_precision=int(metadata.trade_units_precision),
            minimum_trade_size=metadata.minimum_trade_size,
            risk_multiplier=multiplier,
            # The soak-day risk halving is wired when the 14-day run starts
            # (S10); until then the full 0.25% risk applies.
            soak_day=None,
        )

    return _build


def _shadow_recorder(store: Any) -> Any:
    """Adapt the shadow store to the recorder contract (return discarded)."""

    def _record(decisions: Any) -> None:
        store.save_decisions(decisions)

    return _record


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
    *,
    symbols: tuple[str, ...] = DEFAULT_UNIVERSE,
    sources: Any | None = None,
    decision_binding: DecisionBindingService | None = None,
) -> ExternalPaperExecutionBackend:
    if not oanda_is_configured():
        _exit_error(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )
    from alphabrief_execution.broker.risk_context import BrokerRiskContextBuilder

    return ExternalPaperExecutionBackend(
        get_broker_runtime().adapter,
        risk_symbols=symbols,
        risk_context_builder=(BrokerRiskContextBuilder(sources) if sources else None),
        decision_binding=decision_binding,
    )


@contextmanager
def _open_trading_cycle(
    *,
    symbols: tuple[str, ...],
    trading: TradingMode,
    enabled: bool = True,
    database: Path | None = None,
    quantity_override: Decimal | None = None,
    direction_override: str | None = None,
    override_reason: str | None = None,
) -> Iterator[DailyTradingCycle]:
    """One production composition and bounded resource lifetime for all rounds."""
    from alphabrief_execution.broker.recon_store import BrokerReconStore
    from alphabrief_execution.operations.scheduler import HeartbeatStore
    from alphabrief_risk.decision_store import RiskDecisionStore

    resolved = database or _paths.db_path()
    if resolved.resolve() != _paths.db_path().resolve():
        raise ValueError("cycle database must match the runtime data directory")
    with ExitStack() as resources:
        store = AiTradingStore(db_path=resolved)
        resources.callback(store.close)
        market = MarketDataStore(db_path=resolved)
        resources.callback(market.close)
        refresh_errors = _refresh_market_bars(market, symbols)
        news = NewsStore(db_path=resolved)
        resources.callback(news.close)
        news_health = NewsIngestionStore(db_path=resolved)
        resources.callback(news_health.close)
        calls = ModelCallStore(db_path=resolved)
        resources.callback(calls.close)
        shadows = ShadowStore(db_path=resolved)
        resources.callback(shadows.close)
        recon = BrokerReconStore(db_path=resolved)
        resources.callback(recon.close)
        sources = _risk_sources(symbols, recon_store=recon)
        decisions = RiskDecisionStore(db_path=resolved)
        resources.callback(decisions.close)
        warnings = HeartbeatStore(db_path=resolved)
        resources.callback(warnings.close)
        from alphabrief_risk.loss_state import LossStateStore

        losses = LossStateStore(db_path=resolved)
        resources.callback(losses.close)

        def record_warning(decision: RiskDecision) -> None:
            warnings.record_alert(
                severity="warning",
                source="risk_gate",
                task_name="margin",
                message="MARGIN_WARNING: margin utilization exceeds 20%",
                payload={
                    "decision_id": decision.decision_id,
                    "rule_evidence": decision.rule_evidence,
                },
            )

        nav = _nav(sources) if quantity_override is None else None
        model_budget = _model_budget(calls)
        yield DailyTradingCycle(
            committee=build_ai_trading_committee(
                record_sink=_call_recorder(calls), daily_budget=model_budget
            ),
            risk_gate=_risk_gate(
                symbols, nav=nav, require_nav=quantity_override is None
            ),
            execution_backend=(
                _execution_backend(
                    symbols=symbols,
                    sources=sources,
                    decision_binding=DecisionBindingService(decisions),
                )
                if trading == "on"
                else _DisabledBackend()
            ),
            store=store,
            snapshot_loader=_snapshot_loader(
                market, news, news_health, _signal_observation(market), refresh_errors
            ),
            snapshot_refresher=_snapshot_refresher(sources, store),
            enabled=enabled,
            quantity_override=quantity_override,
            direction_override=direction_override,
            override_reason=override_reason,
            trading_mode=trading,
            account_context_provider=_account_context_provider(
                sources,
                trading_day=datetime.now(UTC).date().isoformat(),
                store=store,
                news_store=news,
                universe=symbols,
                loss_store=losses,
            ),
            sizing_provider=_sizing_provider(sources),
            model_budget=model_budget,
            shadow_recorder=_shadow_recorder(shadows),
            risk_warning_recorder=record_warning,
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
    from alphabrief_cli.api_client import require_local_write

    require_local_write("cycle run")

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

    with _open_trading_cycle(
        symbols=symbols,
        trading=trading,
        quantity_override=parsed_units,
        direction_override=force_direction,
        override_reason=reason,
    ) as cycle:
        record = cycle.run(list(symbols))

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
                universe=(instrument,),
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
    from alphabrief_cli.api_client import require_local_write

    require_local_write("cycle close-due")

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
    from alphabrief_cli.api_client import require_local_write

    require_local_write("cycle close")

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
