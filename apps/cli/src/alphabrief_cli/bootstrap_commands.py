"""``alphabrief bootstrap`` — one-command content seeding.

Populates every dashboard page with real, immediately visible content
through the running API (which owns the API-side DuckDB database):

* sample strategy specs (advisory registry)
* news headlines (mock provider — key-less)
* macro indicators (mock provider — key-less)
* a daily alpha brief (real model provider when configured)
* a research debate (real model provider when configured)
* a model evaluation (real provider when ``--real-provider``)

Each step is independent: a failure prints a warning and the remaining
steps still run, so the command is safe to re-run any time.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import typer

from alphabrief_cli.api_client import api_post, is_api_running

bootstrap_app = typer.Typer(
    name="bootstrap",
    help="Seed every dashboard page with real content through the API.",
    no_args_is_help=True,
)

_DEFAULT_UNIVERSE = ["EUR_USD", "BTC-USD", "AAPL", "NVDA", "SPY"]
_MACRO_INDICATORS = ["GDP", "CPI", "UNEMPLOYMENT", "FEDFUNDS", "INDPRO"]

_SAMPLE_STRATEGIES = [
    {
        "strategy_id": "ema_trend_v1",
        "name": "EMA Trend v1",
        "version": "1.0.0",
        "universe": {"symbols": ["SPY"]},
        "timeframe": "1d",
        "entry": {"condition": "close > ema_50"},
        "exit": {"condition": "close < ema_50"},
        "risk": {"max_position_pct": "0.2"},
        "costs": {"fee_bps": "5", "slippage_bps": "10"},
        "evaluation": {
            "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
            "test_period": {"start": "2025-01-01", "end": "2025-12-31"},
        },
    },
    {
        "strategy_id": "mean_reversion_v1",
        "name": "Mean Reversion v1",
        "version": "1.0.0",
        "universe": {"symbols": ["QQQ"]},
        "timeframe": "1d",
        "entry": {"condition": "close < bollinger_lower"},
        "exit": {"condition": "close > sma_20"},
        "risk": {"max_position_pct": "0.15"},
        "costs": {"fee_bps": "5", "slippage_bps": "10"},
        "evaluation": {
            "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
            "test_period": {"start": "2025-01-01", "end": "2025-12-31"},
        },
    },
]


@bootstrap_app.command("all")
def bootstrap_all(
    symbols: str = typer.Option(  # noqa: B008
        ",".join(_DEFAULT_UNIVERSE),
        "--symbols",
        help="Comma-separated symbols for news seeding.",
    ),
    real_provider: bool = typer.Option(  # noqa: B008
        True,
        "--real-provider/--fake-provider",
        help="Use the configured model provider for briefs/debates/evaluations.",
    ),
) -> None:
    """Seed strategies, news, macro, briefs, debates, and model evaluations."""
    if not is_api_running():
        print(
            "bootstrap requires the API server. Start it first with:\n"
            "  alphabrief serve serve\n"
            "or use the launchd-deployed server at http://127.0.0.1:8000.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    universe = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    results: list[tuple[str, str]] = []
    end = datetime.now(UTC)
    start = end - timedelta(days=7)

    def _step(name: str, fn: object) -> None:
        try:
            fn()  # type: ignore[operator]
            results.append((name, "ok"))
        except SystemExit as exc:
            results.append((name, f"failed (exit {exc.code})"))
        except Exception as exc:  # noqa: BLE001 — per-step resilience
            results.append((name, f"failed: {exc}"))

    def _seed_strategies() -> None:
        for spec in _SAMPLE_STRATEGIES:
            api_post("/api/v1/strategies/specs", {"spec": spec, "enabled": False})

    def _seed_news() -> None:
        api_post(
            "/api/v1/news/fetch",
            {
                "source": "mock",
                "symbols": universe,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": 40,
            },
        )

    def _seed_macro() -> None:
        api_post(
            "/api/v1/macro/fetch",
            {
                "source": "mock",
                "indicators": _MACRO_INDICATORS,
                "start": (end - timedelta(days=90)).isoformat(),
                "end": end.isoformat(),
            },
        )

    def _seed_brief() -> None:
        api_post(
            "/api/v1/brief/generate",
            {
                "input_text": (
                    f"Generate the daily alpha brief for {end.date().isoformat()}."
                ),
                "include_news": True,
                "news_symbols": universe[:3],
            },
        )

    def _seed_debate() -> None:
        api_post(
            "/api/v1/research/debate",
            {
                "question": (
                    f"Daily research debate: outlook for {', '.join(universe[:4])}"
                ),
                "time_horizon": "5 trading days",
                "perspectives": ["technical", "fundamental", "risk", "judge"],
            },
        )

    def _seed_evaluation() -> None:
        api_post(
            "/api/v1/models/evaluate",
            {
                "model_id": "openai:deepseek-v4-flash",
                "task_type": "daily_brief",
                "dataset_id": "daily_brief_v1",
                "sample_count": 5,
                "use_real_provider": real_provider,
            },
        )

    _step("strategies", _seed_strategies)
    _step("news", _seed_news)
    _step("macro", _seed_macro)
    _step("brief", _seed_brief)
    _step("debate", _seed_debate)
    _step("evaluation", _seed_evaluation)

    print("\nbootstrap summary:")
    for name, status in results:
        marker = "OK " if status == "ok" else "!! "
        print(f"  {marker}{name}: {status}")
    failed = [name for name, status in results if status != "ok"]
    if failed:
        print(
            f"\n{len(failed)} step(s) failed — re-run `alphabrief bootstrap all` "
            "after fixing the underlying cause.",
            file=sys.stderr,
        )
        raise typer.Exit(1)
    print(
        "\nDone. Open the dashboard at http://127.0.0.1:8000/dashboard — "
        "News / Macro / Briefs / Debates / Models / Strategies now have content."
    )


__all__ = ["bootstrap_app"]
