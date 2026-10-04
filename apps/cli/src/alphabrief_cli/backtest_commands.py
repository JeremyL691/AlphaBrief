"""CLI subcommands for the backtest module."""

from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer
from alphabrief_backtest import VectorizedBacktester, write_backtest_report
from alphabrief_data import generate_basic_features, load_ohlcv_csv
from alphabrief_gym import evaluate_equal_weight_buy_and_hold_v2
from alphabrief_strategy import (
    MovingAverageTrendStrategy,
    StrategySpec,
)

backtest_app = typer.Typer(help="Run deterministic backtests on strategies.")


@backtest_app.command("run")
def run_cmd(
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="Strategy to run: 'momentum', 'random', or registered strategy ID.",
    ),
    instrument: str | None = typer.Option(
        None,
        "--instrument",
        "-i",
        help="Trading instrument (e.g. EUR_USD).",
    ),
    from_date: str | None = typer.Option(
        None,
        "--from",
        "--from-date",
        help="Start date/time (ISO format, e.g. 2026-07-01).",
    ),
    to_date: str | None = typer.Option(
        None,
        "--to",
        "--to-date",
        help="End date/time (ISO format).",
    ),
    spread_bps: str = typer.Option(
        "1.5",
        "--spread-bps",
        help="Spread in basis points (default 1.5).",
    ),
    financing_rate: str = typer.Option(
        "0.0001",
        "--financing-rate",
        help="Daily overnight financing rate (default 0.0001, estimated).",
    ),
    granularity: str = typer.Option(
        "H1",
        "--granularity",
        help="Bar granularity for backtest (H1, D, M15).",
    ),
    save_report: bool = typer.Option(
        True,
        "--save-report/--no-save-report",
        help="Persist report into BacktestReportStore.",
    ),
    data: Path | None = typer.Option(
        None, "--data", help="Path to OHLCV CSV file (legacy engine)."
    ),
    spec: Path | None = typer.Option(
        None, "--spec", help="Path to StrategySpec JSON file (legacy engine)."
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Optional path to write the backtest report JSON."
    ),
    cash: str = typer.Option(
        "10000", "--cash", help="Initial cash as a decimal string."
    ),
    engine: str = typer.Option(
        "legacy", "--engine", help="Backtest engine: 'legacy' or 'env-v2'."
    ),
    symbols: str | None = typer.Option(
        None,
        "--symbols",
        help="Comma-separated symbols for EnvV2 (e.g. BTC-USD,ETH-USD).",
    ),
    max_leverage: str = typer.Option(
        "1", "--max-leverage", help="Max leverage for EnvV2 engine."
    ),
    allow_short: bool = typer.Option(
        False, "--allow-short", help="Allow short selling in EnvV2 engine."
    ),
    fee_bps: str = typer.Option(
        "5", "--fee-bps", help="Fee basis points for EnvV2 engine."
    ),
    slippage_bps: str = typer.Option(
        "5", "--slippage-bps", help="Slippage basis points for EnvV2 engine."
    ),
) -> None:
    """Run a backtest for a given strategy spec and dataset."""
    try:
        initial_cash = Decimal(cash)
    except InvalidOperation as exc:
        print(f"error: invalid --cash value {cash!r}: {exc}", file=sys.stderr)
        sys.exit(1)

    if strategy is not None or instrument is not None:
        _run_oanda_backtest(
            strategy=strategy or "momentum",
            instrument=instrument or "EUR_USD",
            from_date=from_date,
            to_date=to_date,
            output=output,
            initial_cash=initial_cash,
            spread_bps=spread_bps,
            financing_rate=financing_rate,
            granularity=granularity,
            save_report=save_report,
        )
    elif engine == "legacy":
        _run_legacy(
            data=data,
            spec=spec,
            output=output,
            initial_cash=initial_cash,
        )
    elif engine == "env-v2":
        _run_env_v2(
            symbols=symbols,
            output=output,
            initial_cash=initial_cash,
            max_leverage=max_leverage,
            allow_short=allow_short,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    else:
        print(
            f"error: invalid --engine {engine!r}; expected 'legacy' or 'env-v2'",
            file=sys.stderr,
        )
        sys.exit(1)


#: Named builtin strategies runnable without a registered spec: display
#: name plus descriptive entry/exit conditions for the report metadata.
_BUILTIN_STRATEGY_NAMES: dict[str, tuple[str, str, str]] = {
    "momentum": (
        "Momentum Strategy",
        "close > close[-20]",
        "close <= close[-20]",
    ),
    "random": ("Random Strategy", "seeded-random", "seeded-random"),
    "ma_trend": (
        "Moving Average Trend",
        "close > close_sma_3",
        "close <= close_sma_3",
    ),
}


def _run_oanda_backtest(
    *,
    strategy: str,
    instrument: str,
    from_date: str | None,
    to_date: str | None,
    output: Path | None,
    initial_cash: Decimal,
    spread_bps: str,
    financing_rate: str,
    granularity: str,
    save_report: bool,
) -> None:
    from datetime import UTC, date, datetime

    from alphabrief_api.db import BacktestReportStore, StrategySpecStore
    from alphabrief_api.db.market_data import MarketDataStore
    from alphabrief_core import paths as _paths
    from alphabrief_strategy import (
        EvaluationPeriod,
        StrategyCosts,
        StrategyEvaluation,
        StrategyProtocol,
        StrategyRisk,
        StrategyRule,
        StrategySpec,
        StrategyUniverse,
        resolve_builtin_runner,
    )

    try:
        spread_dec = Decimal(spread_bps)
    except InvalidOperation as exc:
        print(
            f"error: invalid --spread-bps value {spread_bps!r}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        financing_dec = Decimal(financing_rate)
    except InvalidOperation as exc:
        print(
            f"error: invalid --financing-rate value {financing_rate!r}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    from_dt: datetime | None = None
    if from_date:
        try:
            if "T" in from_date:
                from_dt = datetime.fromisoformat(from_date)
            else:
                from_d = date.fromisoformat(from_date)
                from_dt = datetime(from_d.year, from_d.month, from_d.day, tzinfo=UTC)
            if from_dt.tzinfo is None:
                from_dt = from_dt.replace(tzinfo=UTC)
        except ValueError as exc:
            print(f"error: invalid --from date {from_date!r}: {exc}", file=sys.stderr)
            sys.exit(1)

    to_dt: datetime | None = None
    if to_date:
        try:
            if "T" in to_date:
                to_dt = datetime.fromisoformat(to_date)
            else:
                to_d = date.fromisoformat(to_date)
                to_dt = datetime(
                    to_d.year, to_d.month, to_d.day, 23, 59, 59, tzinfo=UTC
                )
            if to_dt.tzinfo is None:
                to_dt = to_dt.replace(tzinfo=UTC)
        except ValueError as exc:
            print(f"error: invalid --to date {to_date!r}: {exc}", file=sys.stderr)
            sys.exit(1)

    # Query exactly the requested granularity. Loading without the suffix
    # would dedupe bars by (symbol, timestamp) across granularities and
    # silently drop candles whose timestamps collide with another series.
    store = MarketDataStore(db_path=_paths.db_path())
    try:
        all_bars = store.get_bar_models(
            instrument,
            data_version_suffix=f":M:{granularity.upper()}",
        )
    finally:
        store.close()

    if not all_bars:
        print(
            f"error: no {granularity.upper()} bars found in database for "
            f"instrument {instrument}",
            file=sys.stderr,
        )
        sys.exit(1)

    selected_bars = list(all_bars)

    # Filter by date range
    if from_dt is not None:
        selected_bars = [b for b in selected_bars if b.timestamp >= from_dt]
    if to_dt is not None:
        selected_bars = [b for b in selected_bars if b.timestamp <= to_dt]

    selected_bars.sort(key=lambda b: b.timestamp)

    if len(selected_bars) < 2:
        print(
            f"error: insufficient bars (need >= 2, got {len(selected_bars)}) "
            f"for {instrument} in selected range",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve strategy
    strat_obj: StrategyProtocol
    spec_obj: StrategySpec
    strat_name: str

    if strategy in _BUILTIN_STRATEGY_NAMES:
        strat_name, entry_cond, exit_cond = _BUILTIN_STRATEGY_NAMES[strategy]
        resolved_runner = resolve_builtin_runner(strategy)
        assert resolved_runner is not None  # builtin names always resolve
        strat_obj = resolved_runner
        spec_obj = StrategySpec(
            strategy_id=strategy,
            name=strat_name,
            version="1.0.0",
            universe=StrategyUniverse(symbols=[instrument]),
            timeframe=granularity,
            entry=StrategyRule(condition=entry_cond),
            exit=StrategyRule(condition=exit_cond),
            risk=StrategyRisk(max_position_pct=Decimal("1.0")),
            costs=StrategyCosts(fee_bps=Decimal("5"), slippage_bps=Decimal("5")),
            evaluation=StrategyEvaluation(
                train_period=EvaluationPeriod(
                    start=date(2024, 1, 1), end=date(2025, 12, 31)
                ),
                test_period=EvaluationPeriod(
                    start=date(2026, 1, 1), end=date(2026, 12, 31)
                ),
            ),
        )
    else:
        spec_store = StrategySpecStore(db_path=_paths.db_path())
        try:
            registered = spec_store.get_spec(strategy)
        finally:
            spec_store.close()

        if registered is None:
            print(f"error: unknown strategy {strategy!r}", file=sys.stderr)
            sys.exit(1)
        spec_obj = StrategySpec.model_validate(registered["spec"])
        strat_name = spec_obj.name
        resolved = resolve_builtin_runner(strategy)
        if resolved is None:
            print(f"error: unknown strategy {strategy!r}", file=sys.stderr)
            sys.exit(1)
        strat_obj = resolved

    backtester = VectorizedBacktester(
        initial_cash=initial_cash,
        spread_bps=spread_dec,
        financing_rate_daily=financing_dec,
        financing_estimated=True,
        integer_units=True,
    )
    try:
        report = backtester.run(strat_obj, spec=spec_obj, bars=selected_bars)
    except Exception as exc:
        print(f"error: backtest run failed: {exc}", file=sys.stderr)
        sys.exit(1)

    report_id = "unpersisted"
    if save_report:
        rep_store = BacktestReportStore(db_path=_paths.db_path())
        try:
            report_dict = json.loads(report.model_dump_json())
            report_id = rep_store.save_report(
                report_dict,
                symbol=instrument,
                strategy_name=strat_name,
                report_engine="vectorized",
            )
        finally:
            rep_store.close()

    print(f"report_id: {report_id}")
    print(f"strategy_id: {report.strategy_id}")
    print(f"symbol: {report.symbol}")
    print(f"bars_count: {len(selected_bars)}")
    print(f"initial_cash: {report.initial_cash}")
    print(f"final_value: {report.final_value}")
    print(f"total_return: {report.metrics.total_return}")
    print(f"trade_count: {report.metrics.trade_count}")
    print(f"win_rate: {report.metrics.win_rate}")
    print(f"spread_cost: {report.metrics.spread_cost_total}")
    print(
        f"financing_cost: {report.metrics.financing_cost_total} "
        f"({report.metrics.financing_cost_note})"
    )
    print(f"integer_units: {report.integer_units}")

    if output is not None:
        try:
            write_backtest_report(report, output)
        except OSError as exc:
            print(f"error: could not write report to {output}: {exc}", file=sys.stderr)
            sys.exit(1)


def _run_legacy(
    *,
    data: Path | None,
    spec: Path | None,
    output: Path | None,
    initial_cash: Decimal,
) -> None:
    if data is None:
        print("error: --data is required for legacy engine", file=sys.stderr)
        sys.exit(1)
    if spec is None:
        print("error: --spec is required for legacy engine", file=sys.stderr)
        sys.exit(1)

    try:
        spec_payload = spec.read_text()
    except OSError as exc:
        print(f"error: could not read spec file {spec}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        strategy_spec = StrategySpec.model_validate_json(spec_payload)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {spec}: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"error: invalid StrategySpec in {spec}: {exc}", file=sys.stderr)
        sys.exit(1)

    symbol = strategy_spec.universe.symbols[0]

    try:
        bars = load_ohlcv_csv(
            data,
            symbol=symbol,
            source="local-csv",
            data_version="v1",
        )
    except (OSError, ValueError) as exc:
        print(f"error: could not load CSV {data}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        features = generate_basic_features(bars)
    except ValueError as exc:
        print(f"error: could not generate features: {exc}", file=sys.stderr)
        sys.exit(1)

    strategy = MovingAverageTrendStrategy()
    backtester = VectorizedBacktester(initial_cash=initial_cash)
    try:
        report = backtester.run(
            strategy, spec=strategy_spec, bars=bars, features=features
        )
    except Exception as exc:
        print(f"error: backtest run failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"strategy_id: {report.strategy_id}")
    print(f"symbol: {report.symbol}")
    print(f"initial_cash: {report.initial_cash}")
    print(f"final_value: {report.final_value}")
    print(f"total_return: {report.metrics.total_return}")
    print(f"trade_count: {report.metrics.trade_count}")
    print(f"win_rate: {report.metrics.win_rate}")

    if output is not None:
        try:
            write_backtest_report(report, output)
        except OSError as exc:
            print(f"error: could not write report to {output}: {exc}", file=sys.stderr)
            sys.exit(1)


def _run_env_v2(
    *,
    symbols: str | None,
    output: Path | None,
    initial_cash: Decimal,
    max_leverage: str,
    allow_short: bool,
    fee_bps: str,
    slippage_bps: str,
) -> None:
    from alphabrief_api.db.market_data import MarketDataStore
    from alphabrief_core import Bar as _Bar
    from alphabrief_gym import env_v2_report_to_dict

    if not symbols:
        print("error: --symbols is required for env-v2 engine", file=sys.stderr)
        sys.exit(1)

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        print("error: --symbols must contain at least one symbol", file=sys.stderr)
        sys.exit(1)

    try:
        max_lev = Decimal(max_leverage)
    except InvalidOperation as exc:
        print(
            f"error: invalid --max-leverage value "
            f"{max_leverage!r}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        fee = Decimal(fee_bps)
    except InvalidOperation as exc:
        print(f"error: invalid --fee-bps value {fee_bps!r}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        slip = Decimal(slippage_bps)
    except InvalidOperation as exc:
        print(
            f"error: invalid --slippage-bps value "
            f"{slippage_bps!r}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    store = MarketDataStore()
    try:
        bars_by_symbol = store.get_bar_models_for_symbols(symbol_list)
    finally:
        store.close()

    missing = [s for s in symbol_list if len(bars_by_symbol.get(s, [])) == 0]
    if missing:
        print(
            f"error: no bars found for symbols: {', '.join(sorted(missing))}",
            file=sys.stderr,
        )
        sys.exit(1)

    insufficient = [s for s in symbol_list if len(bars_by_symbol.get(s, [])) < 2]
    if insufficient:
        print(
            f"error: insufficient bars (need >= 2) for symbols: "
            f"{', '.join(sorted(insufficient))}",
            file=sys.stderr,
        )
        sys.exit(1)

    bar_counts = {s: len(bars_by_symbol[s]) for s in symbol_list}
    if len(set(bar_counts.values())) != 1:
        print(
            f"error: mismatched bar counts across symbols: {bar_counts}",
            file=sys.stderr,
        )
        sys.exit(1)

    flat_bars: list[_Bar] = []
    for sym in sorted(bars_by_symbol.keys()):
        flat_bars.extend(bars_by_symbol[sym])

    try:
        report = evaluate_equal_weight_buy_and_hold_v2(
            flat_bars,
            initial_cash=initial_cash,
            max_leverage=max_lev,
            allow_short=allow_short,
            fee_bps=fee,
            slippage_bps=slip,
        )
    except Exception as exc:
        print(f"error: env-v2 backtest failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("engine: env-v2")
    print(f"steps: {report.steps}")
    print(f"initial_value: {report.initial_value}")
    print(f"final_value: {report.final_value}")
    print(f"total_return: {report.total_return}")
    print(f"max_drawdown: {report.max_drawdown}")
    print(f"trade_count: {report.trade_count}")
    print(f"final_leverage: {report.final_leverage}")
    print("costs:")
    print(f"  slippage_cost: {report.costs.slippage_cost}")
    print(f"  market_impact_cost: {report.costs.market_impact_cost}")
    print(f"  borrow_cost: {report.costs.borrow_cost}")
    print(f"  total_cost: {report.costs.total_cost}")

    if output is not None:
        report_dict = env_v2_report_to_dict(report)
        try:
            output.write_text(json.dumps(report_dict, indent=2, default=str))
        except OSError as exc:
            print(f"error: could not write report to {output}: {exc}", file=sys.stderr)
            sys.exit(1)


__all__ = ["backtest_app"]