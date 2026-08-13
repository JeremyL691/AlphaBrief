"""Margin, leverage, loss, drawdown, and loss-streak rules (M08-W04).

Binds new exposure to broker-fresh margin evidence and durable realized
and unrealized daily loss, rolling drawdown, high-water mark, day-start
equity, and consecutive-loss state (REQ-RISK-003, REQ-RISK-004,
REQ-PLAT-005). Every rule is deterministic, Decimal-safe, and
fail-closed: missing or stale margin, PnL, high-water, day-start,
loss-streak, or equity state rejects new exposure and never silently
disables a configured rule (AC-M08-W04-03).

Durable day and high-water values live in :class:`LossStateStore`
(AC-M08-W04-02): they survive restart and can never reset, move
backward, or be replaced with current equity to widen an allowable
limit.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("margin/loss rule decimal values must not be floats")
    return value


class MarginEvidence(BaseModel):
    """One broker-fresh margin snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    nav: Decimal
    margin_used: Decimal = Decimal("0")
    margin_available: Decimal = Decimal("0")
    projected_leverage: Decimal | None = None
    captured_at: datetime
    source_id: str = Field(min_length=1)

    @field_validator(
        "nav", "margin_used", "margin_available", "projected_leverage",
        mode="before",
    )
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class DailyLossEvidence(BaseModel):
    """One realized + unrealized daily PnL observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day_start_equity: Decimal | None = None
    equity_now: Decimal
    realized_day_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    captured_at: datetime

    @field_validator(
        "day_start_equity", "equity_now", "realized_day_pnl",
        "unrealized_pnl", mode="before",
    )
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class EquityPoint(BaseModel):
    """One durable equity observation for rolling drawdown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recorded_at: datetime
    equity: Decimal

    @field_validator("equity", mode="before")
    @classmethod
    def equity_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class DrawdownEvidence(BaseModel):
    """One drawdown observation: high-water mark plus a rolling window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    high_water_mark: Decimal | None = None
    equity_now: Decimal
    rolling_window: tuple[EquityPoint, ...] = ()

    @field_validator("high_water_mark", "equity_now", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class LossStreakEvidence(BaseModel):
    """One consecutive-loss observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    consecutive_losses: int | None = None
    last_day_pnl: Decimal | None = None

    @field_validator("last_day_pnl", mode="before")
    @classmethod
    def pnl_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class MarginLossLimits(BaseModel):
    """One deterministic limit set (None = unconfigured)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_margin_utilization_pct: Decimal | None = None
    min_margin_available_pct: Decimal | None = None
    max_leverage: Decimal | None = None
    max_daily_loss_pct: Decimal | None = None
    max_rolling_drawdown_pct: Decimal | None = None
    max_drawdown_from_hwm_pct: Decimal | None = None
    max_consecutive_losses: int | None = None

    @field_validator(
        "max_margin_utilization_pct",
        "min_margin_available_pct",
        "max_leverage",
        "max_daily_loss_pct",
        "max_rolling_drawdown_pct",
        "max_drawdown_from_hwm_pct",
        mode="before",
    )
    @classmethod
    def limits_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class MarginLossRuleResult(BaseModel):
    """One stable typed rule verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str = Field(min_length=1)
    passed: bool
    value: str
    ceiling: str
    detail: str = ""


class MarginLossRuleError(RuntimeError):
    """A classified fail-closed rule failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"margin/loss rule failed ({kind}): {detail}")


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        raise MarginLossRuleError(
            "invalid_denominator", f"denominator {denominator} is not positive"
        )
    return numerator / denominator


def evaluate_margin_loss_rules(
    *,
    margin: MarginEvidence,
    daily_loss: DailyLossEvidence,
    drawdown: DrawdownEvidence,
    loss_streak: LossStreakEvidence,
    limits: MarginLossLimits,
    evidence_max_age_seconds: int = 300,
    clock: Callable[[], datetime] | None = None,
) -> tuple[MarginLossRuleResult, ...]:
    """Evaluate every configured rule fail-closed against the evidence."""
    results: list[MarginLossRuleResult] = []

    def _check(
        rule: str,
        passed: bool,
        value: str,
        ceiling: str,
        detail: str,
    ) -> None:
        results.append(
            MarginLossRuleResult(
                rule=rule, passed=passed, value=value, ceiling=ceiling, detail=detail
            )
        )

    now = (clock or (lambda: datetime.now(UTC)))()
    age = (now - margin.captured_at).total_seconds()
    if age > evidence_max_age_seconds:
        _check(
            "margin_fresh",
            False,
            f"{age:.1f}s",
            f"{evidence_max_age_seconds}s",
            "margin evidence is stale",
        )
    else:
        _check(
            "margin_fresh",
            True,
            f"{age:.1f}s",
            f"{evidence_max_age_seconds}s",
            "margin evidence is fresh",
        )

    if limits.max_margin_utilization_pct is not None:
        try:
            utilization = _pct(margin.margin_used, margin.nav)
        except MarginLossRuleError as exc:
            _check(
                "margin_utilization", False, "unknown",
                str(limits.max_margin_utilization_pct), exc.detail,
            )
        else:
            _check(
                "margin_utilization",
                utilization <= limits.max_margin_utilization_pct,
                str(utilization),
                str(limits.max_margin_utilization_pct),
                "margin utilization within limit"
                if utilization <= limits.max_margin_utilization_pct
                else "margin utilization exceeds limit",
            )

    if limits.min_margin_available_pct is not None:
        try:
            available_pct = _pct(margin.margin_available, margin.nav)
        except MarginLossRuleError as exc:
            _check(
                "closeout_proximity", False, "unknown",
                str(limits.min_margin_available_pct), exc.detail,
            )
        else:
            _check(
                "closeout_proximity",
                available_pct >= limits.min_margin_available_pct,
                str(available_pct),
                str(limits.min_margin_available_pct),
                "margin available above closeout floor"
                if available_pct >= limits.min_margin_available_pct
                else "margin available at or below closeout floor",
            )

    if limits.max_leverage is not None:
        if margin.projected_leverage is None:
            _check(
                "projected_leverage", False, "unknown",
                str(limits.max_leverage), "no leverage evidence",
            )
        else:
            _check(
                "projected_leverage",
                margin.projected_leverage <= limits.max_leverage,
                str(margin.projected_leverage),
                str(limits.max_leverage),
                "projected leverage within limit"
                if margin.projected_leverage <= limits.max_leverage
                else "projected leverage exceeds limit",
            )

    if limits.max_daily_loss_pct is not None:
        if daily_loss.day_start_equity is None:
            _check(
                "daily_loss", False, "unknown",
                str(limits.max_daily_loss_pct), "no day-start equity",
            )
        else:
            try:
                loss_pct = _pct(
                    daily_loss.day_start_equity - daily_loss.equity_now,
                    daily_loss.day_start_equity,
                )
            except MarginLossRuleError as exc:
                _check(
                    "daily_loss", False, "unknown",
                    str(limits.max_daily_loss_pct), exc.detail,
                )
            else:
                _check(
                    "daily_loss",
                    loss_pct <= limits.max_daily_loss_pct,
                    str(loss_pct),
                    str(limits.max_daily_loss_pct),
                    "daily realized+unrealized loss within limit"
                    if loss_pct <= limits.max_daily_loss_pct
                    else "daily realized+unrealized loss exceeds limit",
                )

    if limits.max_rolling_drawdown_pct is not None:
        window = drawdown.rolling_window
        if not window:
            _check(
                "rolling_drawdown", False, "unknown",
                str(limits.max_rolling_drawdown_pct),
                "no rolling equity window",
            )
        else:
            peak = max(point.equity for point in window)
            current = window[-1].equity
            try:
                drawdown_pct = _pct(peak - current, peak)
            except MarginLossRuleError as exc:
                _check(
                    "rolling_drawdown", False, "unknown",
                    str(limits.max_rolling_drawdown_pct), exc.detail,
                )
            else:
                _check(
                    "rolling_drawdown",
                    drawdown_pct <= limits.max_rolling_drawdown_pct,
                    str(drawdown_pct),
                    str(limits.max_rolling_drawdown_pct),
                    "rolling drawdown within limit"
                    if drawdown_pct <= limits.max_rolling_drawdown_pct
                    else "rolling drawdown exceeds limit",
                )

    if limits.max_drawdown_from_hwm_pct is not None:
        if drawdown.high_water_mark is None:
            _check(
                "drawdown_from_hwm", False, "unknown",
                str(limits.max_drawdown_from_hwm_pct),
                "no high-water mark",
            )
        else:
            try:
                hwm_drawdown = _pct(
                    drawdown.high_water_mark - drawdown.equity_now,
                    drawdown.high_water_mark,
                )
            except MarginLossRuleError as exc:
                _check(
                    "drawdown_from_hwm", False, "unknown",
                    str(limits.max_drawdown_from_hwm_pct), exc.detail,
                )
            else:
                _check(
                    "drawdown_from_hwm",
                    hwm_drawdown <= limits.max_drawdown_from_hwm_pct,
                    str(hwm_drawdown),
                    str(limits.max_drawdown_from_hwm_pct),
                    "drawdown from high-water mark within limit"
                    if hwm_drawdown <= limits.max_drawdown_from_hwm_pct
                    else "drawdown from high-water mark exceeds limit",
                )

    if limits.max_consecutive_losses is not None:
        if loss_streak.consecutive_losses is None:
            _check(
                "consecutive_losses", False, "unknown",
                str(limits.max_consecutive_losses),
                "no loss-streak state",
            )
        else:
            _check(
                "consecutive_losses",
                loss_streak.consecutive_losses <= limits.max_consecutive_losses,
                str(loss_streak.consecutive_losses),
                str(limits.max_consecutive_losses),
                "consecutive losses within limit"
                if loss_streak.consecutive_losses <= limits.max_consecutive_losses
                else "consecutive losses exceed limit",
            )

    return tuple(results)


__all__ = [
    "DailyLossEvidence",
    "DrawdownEvidence",
    "EquityPoint",
    "LossStreakEvidence",
    "MarginEvidence",
    "MarginLossLimits",
    "MarginLossRuleError",
    "MarginLossRuleResult",
    "evaluate_margin_loss_rules",
]
