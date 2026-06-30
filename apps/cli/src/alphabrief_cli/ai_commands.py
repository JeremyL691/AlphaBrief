"""CLI subcommands for the AI Trading Committee.

Commands
--------

- ``ai run``      — run one daily cycle for the supplied universe.
- ``ai status``   — feature-flag state + discipline config + cycle count.
- ``ai history``  — recent cycles, newest-first.
- ``ai rules``    — active discipline config + prompt version + role list.
- ``ai show``     — full JSON record for a single cycle.

The run command proxies through the API when the server is running
and falls back to an in-process paper cycle otherwise. Both paths use
the same ``DailyTradingCycle`` and ``RiskGate`` classes — there is no
separate CLI-only execution path.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import typer
from alphabrief_api.db import AiTradingStore
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    DisciplineConfig,
    MarketSnapshot,
    SnapshotLoader,
    TradingCommittee,
    build_ai_trading_committee,
    is_ai_trading_enabled,
    is_live_trading_unlocked,
)

from alphabrief_cli.api_client import is_api_running

ai_app = typer.Typer(help="AI Trading Committee — multi-role paper cycle.")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_store() -> AiTradingStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return AiTradingStore(db_path=db_dir / "alphabrief.db")
    return AiTradingStore()


def _dump(payload: object, *, pretty: bool, default: bool = False) -> None:
    json.dump(
        payload,
        sys.stdout,
        indent=2 if pretty else None,
        sort_keys=True,
        default=str if default else None,
    )
    sys.stdout.write("\n")


def _exit_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def _api_url(path: str) -> str:
    base = os.environ.get("ALPHABRIEF_API_URL", "http://127.0.0.1:8000")
    return f"{base}{path}"


def _read_api_json(path: str) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(_api_url(path), timeout=5) as response:
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"error: failed to reach {_api_url(path)}: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Offline-cycle builder (mirrors the API run path)
# ---------------------------------------------------------------------------


def _build_committee() -> TradingCommittee:
    return build_ai_trading_committee()


def _build_broker() -> PaperBroker:
    return PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )


def _build_risk_gate(symbols: list[str]) -> RiskGate:
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset(symbols),
        )
    )


def _build_loader(
    symbols: list[str],
    reference_prices: dict[str, Decimal] | None,
) -> SnapshotLoader:
    overrides = reference_prices or {}

    def _loader(symbol: str) -> MarketSnapshot | None:
        if symbol not in symbols:
            return None
        ref = overrides.get(symbol, Decimal("100"))
        return MarketSnapshot(
            symbol=symbol,
            reference_price=ref,
            recent_return_pct=Decimal("0"),
            recent_volume=Decimal("1000"),
            data_version="cli-runner-v1",
            captured_at=datetime.now(UTC),
        )

    return _loader


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@ai_app.command("status")
def status_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Print feature-flag state, discipline config, and cycle count."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/ai/status"), pretty=pretty)
        return

    store = _open_store()
    try:
        cycles = store.list_cycles(limit=200)
    finally:
        store.close()
    _dump(
        {
            "ai_trading_enabled": is_ai_trading_enabled(),
            "live_trading_enabled": is_live_trading_unlocked(),
            "discipline": DisciplineConfig().model_dump(mode="json"),
            "cycle_count": len(cycles),
        },
        pretty=pretty,
    )


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@ai_app.command("run")
def run_cmd(
    symbols: str = typer.Option(  # noqa: B008
        ...,
        "--symbols",
        help="Comma-separated universe, e.g. 'SPY,QQQ,IVV'.",
    ),
    reference_prices: str | None = typer.Option(  # noqa: B008
        None,
        "--reference-prices",
        help=(
            "Optional inline JSON mapping symbol -> decimal reference "
            "price, e.g. '{\"SPY\": 450.00}'."
        ),
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Run one daily cycle for the supplied universe."""
    if is_live_trading_unlocked():
        _exit_error(
            "ALPHABRIEF_LIVE_TRADING_ENABLED is set; AI trading is paper-only"
        )
    if not is_ai_trading_enabled():
        _exit_error(
            "ALPHABRIEF_AI_TRADING_ENABLED is not set; refusing to execute"
        )

    parsed_symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    if not parsed_symbols:
        _exit_error("--symbols must contain at least one non-empty symbol")

    parsed_prices: dict[str, Decimal] | None = None
    if reference_prices:
        try:
            raw_prices = json.loads(reference_prices)
        except json.JSONDecodeError as exc:
            _exit_error(f"invalid JSON in --reference-prices: {exc}")
        if not isinstance(raw_prices, dict):
            _exit_error("--reference-prices must be a JSON object")
        try:
            parsed_prices = {k: Decimal(v) for k, v in raw_prices.items()}
        except Exception as exc:
            _exit_error(f"--reference-prices contains invalid decimal: {exc}")

    if is_api_running():
        try:
            import urllib.error
            import urllib.request

            body = json.dumps(
                {
                    "symbols": parsed_symbols,
                    "reference_prices": (
                        {k: format(v, "f") for k, v in parsed_prices.items()}
                        if parsed_prices
                        else None
                    ),
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                _api_url("/api/v1/ai/run"),
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            _dump(payload, pretty=pretty)
            return
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            print(
                f"warning: API run failed ({exc}); falling back to local cycle",
                file=sys.stderr,
            )

    store = _open_store()
    try:
        cycle = DailyTradingCycle(
            committee=_build_committee(),
            risk_gate=_build_risk_gate(parsed_symbols),
            broker=_build_broker(),
            store=store,
            snapshot_loader=_build_loader(parsed_symbols, parsed_prices),
            enabled=True,
        )
        record = cycle.run(parsed_symbols)
    finally:
        store.close()

    _dump(
        {
            "cycle_id": record.cycle_id,
            "trading_day": record.trading_day,
            "outcome": record.outcome,
            "summary": record.summary,
            "plan_count": len(record.plans),
            "attempt_count": len(record.attempts),
            "votes": [v.model_dump(mode="json") for v in record.votes],
            "plans": [p.model_dump(mode="json") for p in record.plans],
            "attempts": [a.model_dump(mode="json") for a in record.attempts],
        },
        pretty=pretty,
    )


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


@ai_app.command("history")
def history_cmd(
    limit: int = typer.Option(  # noqa: B008
        20,
        "--limit",
        min=1,
        max=200,
        help="Maximum number of cycles to return (clamped to [1, 200]).",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List recent cycles, newest-first."""
    if is_api_running():
        _dump(_read_api_json(f"/api/v1/ai/history?limit={limit}"), pretty=pretty)
        return
    store = _open_store()
    try:
        summaries = store.list_cycles(limit=limit)
    finally:
        store.close()
    _dump(
        {
            "cycles": [
                {
                    "cycle_id": s.cycle_id,
                    "trading_day": s.trading_day,
                    "symbols": list(s.symbols),
                    "plan_count": s.plan_count,
                    "attempt_count": s.attempt_count,
                    "executed_count": s.executed_count,
                    "blocked_count": s.blocked_count,
                    "outcome": s.outcome,
                    "enabled": s.enabled,
                    "live_trading_enabled": s.live_trading_enabled,
                    "created_at": s.created_at,
                }
                for s in summaries
            ]
        },
        pretty=pretty,
    )


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@ai_app.command("show")
def show_cmd(
    cycle_id: str = typer.Argument(..., help="Cycle ID to look up."),  # noqa: B008
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Print the full JSON record for a single cycle."""
    if is_api_running():
        _dump(
            _read_api_json(f"/api/v1/ai/cycles/{cycle_id}"), pretty=pretty
        )
        return
    store = _open_store()
    try:
        record = store.get_cycle(cycle_id)
    finally:
        store.close()
    if record is None:
        _exit_error(f"cycle {cycle_id!r} not found")
    _dump(record, pretty=pretty)


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


@ai_app.command("rules")
def rules_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Print the active discipline rules + prompt version + role list."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/ai/rules"), pretty=pretty)
        return
    _dump(
        {
            "discipline": DisciplineConfig().model_dump(mode="json"),
            "prompt_version": "aitrader-v1",
            "roles": ["technical", "fundamental", "risk", "manager"],
        },
        pretty=pretty,
    )


__all__ = ["ai_app"]
