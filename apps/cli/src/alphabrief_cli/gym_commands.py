"""CLI subcommands for reinforcement learning gym environments.

Provides `alphabrief gym demo` to run a simulation episode using
stored OANDA bars without placing any real or broker orders.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal

import typer
from alphabrief_api.db import MarketDataStore
from alphabrief_core import paths as _paths
from alphabrief_gym import evaluate_equal_weight_buy_and_hold_v2

gym_app = typer.Typer(
    help="Gym simulation environments on OANDA bars (offline only)."
)


@gym_app.command("demo")
def demo_cmd(
    instrument: str = typer.Option(  # noqa: B008
        "EUR_USD",
        "--instrument",
        "-i",
        help="Forex instrument to run gym demo on.",
    ),
    granularity: str = typer.Option(  # noqa: B008
        "H1",
        "--granularity",
        "-g",
        help="Candle granularity (M15, H1, H4, D).",
    ),
    initial_cash: float = typer.Option(  # noqa: B008
        10000.0,
        "--initial-cash",
        help="Starting simulation cash balance.",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
        help="Format JSON output.",
    ),
) -> None:
    """Run one offline gym simulation episode using stored OANDA bars."""
    market_store = MarketDataStore(db_path=_paths.db_path())
    try:
        bars = market_store.get_bar_models(
            instrument,
            data_version_suffix=f":M:{granularity}",
        )
        if not bars:
            bars = market_store.get_bar_models(instrument)
    finally:
        market_store.close()

    if not bars:
        print(
            f"error: No stored OANDA bars found for instrument {instrument}. "
            f"Run 'alphabrief data fetch' first to download practice candles.",
            file=sys.stderr,
        )
        sys.exit(1)

    sorted_bars = sorted(bars, key=lambda b: b.timestamp)

    report = evaluate_equal_weight_buy_and_hold_v2(
        bars=sorted_bars,
        initial_cash=Decimal(str(initial_cash)),
    )

    summary = {
        "status": "completed",
        "mode": "gym_offline_simulation",
        "live_trading": False,
        "instrument": instrument,
        "granularity": granularity,
        "bar_count": len(sorted_bars),
        "steps": report.steps,
        "start_time": sorted_bars[0].timestamp.isoformat(),
        "end_time": sorted_bars[-1].timestamp.isoformat(),
        "initial_value": float(report.initial_value),
        "final_value": float(report.final_value),
        "total_return": float(report.total_return),
        "max_drawdown": float(report.max_drawdown),
        "trade_count": report.trade_count,
        "total_cost": float(report.costs.total_cost),
        "execution_note": (
            "Gym episode evaluated purely on stored OANDA bars; "
            "zero broker orders placed."
        ),
    }

    if pretty:
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps(summary))


__all__ = ["gym_app"]
