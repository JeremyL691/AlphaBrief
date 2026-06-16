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

    if engine == "legacy":
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