"""Daily report command (PROJECT_GUIDE 5.12).

``alphabrief report daily`` gathers one UTC day of facts from the runtime
database and writes ``reports/daily/YYYY-MM-DD.md`` plus ``.json``. Every
section is a store query; a section without evidence says so instead of
printing a plausible number. The command never calls a broker or a model.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import typer
from alphabrief_api.db.ai_trading import AiTradingStore
from alphabrief_api.db.market_data import MarketDataStore
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_api.db.paper import PaperStore
from alphabrief_core import paths as _paths
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_trader.daily_report import DailyReportData, write_daily_report
from alphabrief_trader.shadow_store import ShadowStore

report_app = typer.Typer(help="Generate operator reports from the database.")


def _dump(payload: object, *, pretty: bool) -> None:
    json.dump(payload, sys.stdout, indent=2 if pretty else None, default=str)
    sys.stdout.write("\n")


def _day(raw: str | None) -> str:
    if raw is None:
        return datetime.now(UTC).date().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise typer.BadParameter(f"--date must be YYYY-MM-DD: {raw!r}") from exc


def _cycle_payload(store: AiTradingStore, cycle_id: str) -> dict[str, Any]:
    """One cycle record as a plain dict (empty when it cannot be read)."""
    raw = store.get_cycle(cycle_id)
    if raw is None:
        return {}
    return raw if isinstance(raw, dict) else raw.model_dump(mode="json")


def _cycles_for_day(store: AiTradingStore, day: str) -> list[dict[str, Any]]:
    summaries = store.list_cycles(limit=500)
    selected = [s for s in summaries if getattr(s, "trading_day", None) == day]
    rows: list[dict[str, Any]] = []
    for summary in selected:
        record = _cycle_payload(store, summary.cycle_id)
        rows.append(
            {
                "cycle_id": summary.cycle_id,
                "trading_day": summary.trading_day,
                "outcome": summary.outcome,
                "plan_count": summary.plan_count,
                "attempt_count": summary.attempt_count,
                "executed_count": summary.executed_count,
                "blocked_count": summary.blocked_count,
                "summary": record.get("summary", ""),
                "created_at": str(summary.created_at),
            }
        )
    # Oldest first, so the day reads in the order it happened.
    return sorted(rows, key=lambda row: str(row["created_at"]))


def _attempts_for_day(store: AiTradingStore, day: str) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for summary in store.list_cycles(limit=500):
        if getattr(summary, "trading_day", None) != day:
            continue
        record = _cycle_payload(store, summary.cycle_id)
        for attempt in record.get("attempts", []):
            attempts.append({**attempt, "cycle_id": summary.cycle_id})
    return attempts


def _model_calls_for_day(store: ModelCallStore, day: str) -> list[dict[str, Any]]:
    calls = store.list_calls(limit=2000)
    return [call for call in calls if str(call.get("created_at", ""))[:10] == day]


def _equity_snapshot(day: str) -> dict[str, Any]:
    """NAV, day-start equity and drawdown, when an account id is configured."""
    from alphabrief_execution.broker.oanda.config import read_oanda_credentials
    from alphabrief_execution.broker.runtime import oanda_is_configured

    if not oanda_is_configured():
        return {"note": "OANDA practice credentials are not configured"}
    # The account id is only used to read the local equity snapshots; it is
    # never printed (reports carry the metrics, not the identifier).
    _, account_id = read_oanda_credentials()
    store = PaperStore(db_path=_paths.db_path())
    try:
        day_start = store.get_day_start_equity(account_id, date.fromisoformat(day))
        latest = store.get_latest_equity(account_id)
        high_water = store.get_high_water_mark(account_id)
    finally:
        store.close()
    if day_start is None and latest is None and high_water is None:
        return {
            "note": (
                "no equity snapshots recorded yet; the runtime stores them "
                "on every account sync (S5)"
            )
        }
    equity: dict[str, Any] = {
        "day_start_equity": None if day_start is None else str(day_start),
        "latest_equity": None if latest is None else str(latest),
        "equity_high_water_mark": None if high_water is None else str(high_water),
    }
    if day_start is not None and latest is not None:
        equity["realized_change"] = str(latest - day_start)
    if high_water is not None and latest is not None and high_water > 0:
        drawdown = (high_water - latest) / high_water
        equity["drawdown_pct"] = str(drawdown * 100)
    return equity


def _reconciliation(day: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    store = BrokerReconStore(db_path=_paths.db_path())
    try:
        snapshots = store.list_snapshots(limit=200)
        freezes = store.list_freezes(only_open=False)
    finally:
        store.close()
    todays = [s for s in snapshots if str(s.captured_at)[:10] == day]
    state: dict[str, Any] = {
        "snapshots": len(todays),
        "clean": sum(1 for s in todays if s.all_match),
        "unclean": sum(1 for s in todays if not s.all_match),
    }
    if todays:
        latest = todays[0]
        state["last_snapshot_at"] = str(latest.captured_at)
        state["last_snapshot_scope"] = latest.scope
        state["last_snapshot_all_match"] = latest.all_match
    freeze_rows = [
        {
            "freeze_id": event.event_id,
            "scope": event.scope,
            "reason": event.reason,
            "created_at": str(event.raised_at),
        }
        for event in freezes
        if str(event.raised_at)[:10] == day
    ]
    return state, freeze_rows


def _market_freshness(symbols: tuple[str, ...]) -> list[dict[str, Any]]:
    store = MarketDataStore(db_path=_paths.db_path())
    rows: list[dict[str, Any]] = []
    try:
        for symbol in symbols:
            bars = store.get_bar_models(symbol)
            if not bars:
                rows.append(
                    {
                        "symbol": symbol,
                        "latest_bar_at": None,
                        "data_version": None,
                        "bars": 0,
                    }
                )
                continue
            latest = bars[-1]
            rows.append(
                {
                    "symbol": symbol,
                    "latest_bar_at": latest.timestamp.isoformat(),
                    "data_version": latest.data_version,
                    "bars": len(bars),
                }
            )
    finally:
        store.close()
    return rows


def _doctor_summary() -> str:
    """The doctor's one-line summary for the report (offline checks only).

    The daily report must not spend network calls or model budget, so it
    embeds the offline half of ``alphabrief doctor`` and names the checks
    it skipped.
    """
    from alphabrief_cli.cycle_commands import DEFAULT_UNIVERSE
    from alphabrief_cli.doctor_commands import run_checks

    try:
        report = run_checks(symbols=DEFAULT_UNIVERSE, include_network=False)
    except Exception as exc:  # noqa: BLE001 - a doctor failure is reported
        return f"doctor unavailable: {type(exc).__name__}: {exc}"
    return f"{report.summary()} (offline checks; network checks skipped)"


@report_app.command("daily")
def daily_cmd(
    report_date: str | None = typer.Option(  # noqa: B008
        None,
        "--date",
        help="UTC day to report on (YYYY-MM-DD). Defaults to today.",
    ),
    out_dir: Path | None = typer.Option(  # noqa: B008
        None,
        "--out-dir",
        help="Directory for the report files. Defaults to the data directory.",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Write the daily report for one UTC day."""
    from alphabrief_cli.api_client import require_local_write

    require_local_write("report daily")

    from alphabrief_cli.cycle_commands import DEFAULT_UNIVERSE

    day = _day(report_date)
    doctor_summary = _doctor_summary()
    store = AiTradingStore(db_path=_paths.db_path())
    model_calls = ModelCallStore(db_path=_paths.db_path())
    shadow = ShadowStore(db_path=_paths.db_path())
    try:
        data = DailyReportData(
            trading_day=day,
            generated_at=datetime.now(UTC),
            cycles=_cycles_for_day(store, day),
            attempts=_attempts_for_day(store, day),
            model_calls=_model_calls_for_day(model_calls, day),
            shadow_decisions=shadow.list_decisions(limit=10000),
            shadow_stats=shadow.scoreboard(),
            reconciliation=_reconciliation(day)[0],
            freezes=_reconciliation(day)[1],
            equity=_equity_snapshot(day),
            market_freshness=_market_freshness(DEFAULT_UNIVERSE),
            doctor_summary=doctor_summary,
        )
        markdown_path, json_path = write_daily_report(data, directory=out_dir)
    finally:
        shadow.close()
        model_calls.close()
        store.close()

    _dump(
        {
            "trading_day": day,
            "markdown": str(markdown_path),
            "json": str(json_path),
            "cycles": len(data.cycles),
            "attempts": len(data.attempts),
            "model_calls": len(data.model_calls),
            "shadow_decisions": len(data.shadow_decisions),
            "risk_rejections": data.rejection_counts(),
        },
        pretty=pretty,
    )


@report_app.command("soak")
def soak_cmd(
    final: bool = typer.Option(  # noqa: B008
        False,
        "--final",
        help="Generate final release soak report (writes to reports/).",
    ),
    out_file: Path | None = typer.Option(  # noqa: B008
        None,
        "--out-file",
        help="Custom output file path for markdown report.",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Write the comprehensive 14-day soak test report."""
    from alphabrief_trader.soak_report import (
        generate_soak_report_data,
        write_soak_report,
    )

    data = generate_soak_report_data()
    md_path, json_path = write_soak_report(data, out_file=out_file, final=final)

    _dump(
        {
            "final": final,
            "markdown": str(md_path),
            "json": str(json_path),
            "qualified_days": data.status.qualified_days,
            "target_days": data.status.target_days,
            "extensions": data.status.extension_days,
            "resets": len(data.status.resets),
            "is_complete": data.status.is_complete,
            "state": data.status.state,
        },
        pretty=pretty,
    )


__all__ = ["daily_cmd", "report_app", "soak_cmd"]

