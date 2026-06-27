"""CLI subcommands for the risk module."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from alphabrief_core import OrderIntent
from alphabrief_research import build_structured_summary
from alphabrief_risk import (
    AccountExposureContext,
    RiskContextDecision,
    RiskGate,
    RiskLimitConfig,
    evaluate_news_macro_risk,
)

risk_app = typer.Typer(help="Inspect risk decisions and KillSwitch state.")


@risk_app.command("status")
def status_cmd() -> None:
    """Show the current RiskGate and KillSwitch status."""
    # ponytail: report on a permissive paper-default RiskGate (the same
    # shape the paper CLI builds). CLI risk commands are read-only and
    # do not mutate the API-side gate.
    gate = RiskGate(
        limits=RiskLimitConfig(trading_enabled=True),
    )
    kill_switch_active = gate.kill_switch.active
    payload = {
        "trading_enabled": gate.limits.trading_enabled,
        "live_trading_enabled": gate.limits.live_trading_enabled,
        "symbol_allowlist": sorted(gate.limits.symbol_allowlist),
        "max_order_value": (
            str(gate.limits.max_order_value)
            if gate.limits.max_order_value is not None
            else None
        ),
        "max_total_exposure": (
            str(gate.limits.max_total_exposure)
            if gate.limits.max_total_exposure is not None
            else None
        ),
        "require_human_review": gate.limits.require_human_review,
        "kill_switch_active": kill_switch_active,
        "kill_switch_reason": gate.kill_switch.reason,
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _parse_risk_context(
    raw: str | None, source_label: str
) -> RiskContextDecision | None:
    """Parse a RiskContextDecision from inline JSON or return None."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"error: invalid JSON in {source_label}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, dict):
        print(
            f"error: {source_label} must be a JSON object",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return RiskContextDecision.model_validate(data)
    except ValueError as exc:
        print(
            f"error: invalid RiskContextDecision in {source_label}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def _parse_optional_decimal(raw: str | None, *, label: str) -> Decimal | None:
    """Parse a ``Decimal`` from a CLI string, or return None.

    Mirrors the API string-transport style for monetary inputs so the
    CLI never has to bridge ``float`` (Pydantic rejects ``float`` on
    the context boundary)."""
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except ArithmeticError as exc:
        print(f"error: invalid decimal in {label}: {exc}", file=sys.stderr)
        sys.exit(1)


def _parse_reference_mark_prices(
    raw: str | None, *, label: str
) -> dict[str, Decimal] | None:
    """Parse a JSON object of ``{symbol: decimal_str}`` into Decimals."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {label}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print(f"error: {label} must be a JSON object", file=sys.stderr)
        sys.exit(1)
    out: dict[str, Decimal] = {}
    for symbol, value in data.items():
        if not isinstance(symbol, str) or not symbol:
            print(
                f"error: {label} keys must be non-empty strings",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            out[symbol] = Decimal(str(value))
        except ArithmeticError as exc:
            print(
                f"error: invalid decimal in {label} for {symbol}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
    return out


@risk_app.command("check")
def check_cmd(
    intent: Path = typer.Option(  # noqa: B008 - typer pattern
        ..., "--intent", help="Path to OrderIntent JSON file."
    ),
    risk_context: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--risk-context",
        help=(
            "Optional RiskContextDecision as inline JSON. When provided, "
            "the gate is tightened by merging risk_tags, OR-ing "
            "requires_human_review, and reducing max_quantity by "
            "suggested_max_position_multiplier. The context can never "
            "relax existing limits."
        ),
    ),
    risk_context_file: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--risk-context-file",
        help="Optional path to a JSON file with a RiskContextDecision.",
    ),
    # Phase 21 R21.x account-context overrides. The CLI builds an
    # AccountExposureContext from these so the new R21.x checks
    # (symbol exposure, concentration, leverage, price deviation, daily
    # loss, drawdown) can be exercised end-to-end through the CLI. The
    # existing ``--total-exposure`` / ``--symbol-exposure`` /
    # ``--cash`` overrides are not present — the defaults built below
    # are a permissive zero-exposure portfolio so callers only have to
    # pass the fields they care about.
    equity: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--equity",
        help=(
            "Optional current account equity (Decimal string). Required "
            "when a max_leverage / max_daily_loss_pct / "
            "max_drawdown_floor_pct rule is configured."
        ),
    ),
    reference_mark_prices: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--reference-mark-prices",
        help=(
            "Optional JSON object of {symbol: decimal_str} mapping the "
            "live mark for each symbol. Consumed by the "
            "max_price_deviation_pct rule."
        ),
    ),
    equity_hwm: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--equity-hwm",
        help=(
            "Optional equity high-water mark (Decimal string). Required "
            "when max_drawdown_floor_pct is configured."
        ),
    ),
    day_start_equity: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--day-start-equity",
        help=(
            "Optional day-start equity (Decimal string). Required when "
            "max_daily_loss_pct is configured."
        ),
    ),
    day_realized_pnl: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--day-realized-pnl",
        help=(
            "Optional day-realized PnL (Decimal string; may be negative "
            "for loss days). Surfaced for audit / diagnostics only."
        ),
    ),
) -> None:
    """Evaluate an OrderIntent JSON file through RiskGate."""
    try:
        payload = intent.read_text()
    except OSError as exc:
        print(f"error: could not read intent file {intent}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        order_intent = OrderIntent.model_validate_json(payload)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {intent}: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"error: invalid OrderIntent in {intent}: {exc}", file=sys.stderr)
        sys.exit(1)

    if risk_context is not None and risk_context_file is not None:
        print(
            "error: --risk-context and --risk-context-file are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(1)

    parsed_context: RiskContextDecision | None = None
    if risk_context is not None:
        parsed_context = _parse_risk_context(risk_context, "--risk-context")
    elif risk_context_file is not None:
        try:
            file_text = risk_context_file.read_text()
        except OSError as exc:
            print(
                f"error: could not read risk context file {risk_context_file}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        parsed_context = _parse_risk_context(
            file_text, f"--risk-context-file {risk_context_file}"
        )

    # Build a permissive zero-exposure AccountExposureContext from the
    # R21.x CLI overrides. Only the fields the caller passed are set;
    # the rest stay None so the gate's fail-closed paths can be
    # exercised explicitly.
    account_ctx_overrides: dict[str, Any] = {
        "current_total_exposure": Decimal("0"),
        "exposure_by_symbol": {},
        "cash": Decimal("0"),
        "account_id": "cli_risk_check",
        "captured_at": datetime.now(UTC),
    }
    parsed_equity = _parse_optional_decimal(equity, label="--equity")
    if parsed_equity is not None:
        account_ctx_overrides["equity"] = parsed_equity
    parsed_marks = _parse_reference_mark_prices(
        reference_mark_prices, label="--reference-mark-prices"
    )
    if parsed_marks is not None:
        account_ctx_overrides["reference_mark_prices"] = parsed_marks
    parsed_hwm = _parse_optional_decimal(equity_hwm, label="--equity-hwm")
    if parsed_hwm is not None:
        account_ctx_overrides["equity_high_water_mark"] = parsed_hwm
    parsed_day_start = _parse_optional_decimal(
        day_start_equity, label="--day-start-equity"
    )
    if parsed_day_start is not None:
        account_ctx_overrides["day_start_equity"] = parsed_day_start
    parsed_day_pnl = _parse_optional_decimal(
        day_realized_pnl, label="--day-realized-pnl"
    )
    if parsed_day_pnl is not None:
        account_ctx_overrides["day_realized_pnl"] = parsed_day_pnl
    try:
        account_context = AccountExposureContext.model_validate(account_ctx_overrides)
    except ValueError as exc:
        print(
            f"error: invalid account context from CLI overrides: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    gate = RiskGate(limits=RiskLimitConfig())
    try:
        decision = gate.evaluate(
            order_intent,
            risk_context=parsed_context,
            account_context=account_context,
        )
    except Exception as exc:
        print(f"error: risk gate evaluation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"decision_id: {decision.decision_id}")
    print(f"approved: {decision.approved}")
    print(f"reason: {decision.reason}")
    print(f"risk_tags: {','.join(decision.risk_tags)}")
    print(f"requires_human_review: {decision.requires_human_review}")
    if parsed_context is not None:
        print(f"applied_risk_context: {parsed_context.decision_id}")


@risk_app.command("context")
def context_cmd(
    headlines: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--headlines",
        help=(
            "Optional path to a JSON file with a list of NewsHeadline "
            "dicts. If omitted, an empty news list is used."
        ),
    ),
    indicators: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--indicators",
        help=(
            "Optional path to a JSON file with a list of "
            "MacroIndicator dicts. If omitted, an empty list is used."
        ),
    ),
    decision_id: str = typer.Option(
        "rctx_cli",
        "--decision-id",
        help="Identifier echoed in the RiskContextDecision.",
    ),
    pretty: bool = typer.Option(
        True,
        "--pretty/--compact",
        help="Pretty-print the JSON output (default: pretty).",
    ),
) -> None:
    """Show the read-only news/macro risk context decision.

    The command is read-only: it never modifies risk limits, never
    places orders, and never writes to any store. Use ``--headlines``
    and ``--indicators`` to feed a one-off summary; otherwise the
    decision is computed from empty inputs and is guaranteed to be
    the no-op (no tightening) variant.
    """
    from alphabrief_news import MacroIndicator, NewsHeadline

    headline_objs: list[NewsHeadline] = []
    if headlines is not None:
        try:
            raw_headlines = json.loads(headlines.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"error: could not load headlines from {headlines}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(raw_headlines, list):
            print(
                "error: --headlines file must contain a JSON array of "
                "NewsHeadline objects",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            headline_objs = [
                NewsHeadline.model_validate(item) for item in raw_headlines
            ]
        except ValueError as exc:
            print(
                f"error: invalid NewsHeadline in {headlines}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    indicator_objs: list[MacroIndicator] = []
    if indicators is not None:
        try:
            raw_indicators = json.loads(indicators.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"error: could not load indicators from {indicators}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(raw_indicators, list):
            print(
                "error: --indicators file must contain a JSON array of "
                "MacroIndicator objects",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            indicator_objs = [
                MacroIndicator.model_validate(item) for item in raw_indicators
            ]
        except ValueError as exc:
            print(
                f"error: invalid MacroIndicator in {indicators}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    summary = build_structured_summary(headline_objs, indicator_objs)
    decision: RiskContextDecision = evaluate_news_macro_risk(
        summary,
        decision_id=decision_id,
    )

    payload = {
        "summary": summary.to_dict(),
        "decision": {
            "requires_human_review": decision.requires_human_review,
            "risk_tags": list(decision.risk_tags),
            "suggested_max_position_multiplier": (
                decision.suggested_max_position_multiplier
            ),
            "notes": list(decision.notes),
            "source_summary_untrusted": decision.source_summary_untrusted,
            "decision_id": decision.decision_id,
            "context_id": decision.context_id,
        },
        "query": {
            "headlines_path": str(headlines) if headlines else None,
            "indicators_path": str(indicators) if indicators else None,
            "decision_id": decision_id,
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    }
    indent = 2 if pretty else None
    json.dump(payload, sys.stdout, indent=indent, sort_keys=True)
    sys.stdout.write("\n")


__all__ = ["risk_app"]
