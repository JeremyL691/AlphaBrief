"""Entry rules from PROJECT_GUIDE 5.7 that the base gate did not cover.

Rules implemented here (each fail-closed, each with a stable rejection
code matching the guide):

* 3 — quote freshness and tradeability (``QUOTE_STALE`` / ``NOT_TRADEABLE``)
* 7 — daily intent caps (``DAILY_INTENT_CAP``)
* 8 — maximum concurrent positions, opens only (``MAX_POSITIONS``)
* 12 — losing-streak instrument freeze (``LOSS_STREAK``)
* 13 — Friday 13:00 UTC onward and weekends (``WEEKEND``)
* 14 — protective orders and a legal size are present (``ORDER_INVALID``)

The rules are pure functions over the intent, the account context, and the
clock, so every one is deterministically testable. They only ever reject:
closing (reduce-only) intents are exempt from every entry rule except rule 3
(a close still needs a fresh, tradeable quote — PROJECT_GUIDE 5.7), because a
position must always be closable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_core import OrderIntent

from alphabrief_risk.account_context import AccountExposureContext

#: Rejection codes, exactly as named in PROJECT_GUIDE 5.7.
RuleCode = str

#: Friday cutoff: no new exposure from 13:00 UTC onward.
FRIDAY_OPEN_CUTOFF_HOUR = 13


@dataclass(frozen=True)
class RuleRejection:
    """One rule rejection with its guide code and evidence."""

    code: RuleCode
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class EntryRulePolicy:
    """Configuration for the entry rules; ``None`` means "not enforced"."""

    max_quote_age_seconds: int | None = None
    require_quote_tradeable: bool = False
    max_daily_opens: int | None = None
    max_daily_symbol_opens: int | None = None
    max_open_positions: int | None = None
    require_protective_orders: bool = False
    block_weekend_and_late_friday: bool = False
    stop_price_tolerance: Decimal = Decimal("0")
    #: Rule 6: block entries while a high-impact event is inside this
    #: window. ``None`` leaves the rule unenforced.
    event_window_minutes: int | None = None
    #: Rule 11: block entries while the drawdown state machine says so.
    #: ``False`` leaves the rule unenforced.
    block_on_drawdown: bool = False


def _is_open_intent(intent: OrderIntent) -> bool:
    """An intent that increases exposure (a close is always allowed)."""
    return not (intent.reduce_only or intent.target_position_pct == 0)


def _protective_order_issues(intent: OrderIntent) -> list[str]:
    """Return the reasons the protective orders are unusable."""
    issues: list[str] = []
    if intent.stop_loss is None:
        issues.append("stop_loss is missing")
    if intent.take_profit is None:
        issues.append("take_profit is missing")
    if intent.quantity is None or intent.quantity <= 0:
        issues.append("quantity must be a positive number of units")
    elif intent.quantity != intent.quantity.to_integral_value():
        issues.append("quantity must be a whole number of units")
    if intent.stop_loss is not None and intent.take_profit is not None:
        if intent.side == "buy" and intent.stop_loss >= intent.take_profit:
            issues.append("a long order needs stop_loss below take_profit")
        if intent.side == "sell" and intent.stop_loss <= intent.take_profit:
            issues.append("a short order needs stop_loss above take_profit")
    return issues


def evaluate_quote_rules(
    intent: OrderIntent,
    *,
    policy: EntryRulePolicy,
    now: datetime,
    account_context: AccountExposureContext | None = None,
) -> tuple[RuleRejection, ...]:
    """Rule 3 alone: quote freshness and tradeability.

    This is the one entry rule that also applies to closes (PROJECT_GUIDE
    5.7): even a reduce-only order is submitted at a price, so it must be
    priced from a fresh quote on a tradeable instrument.
    """
    rejections: list[RuleRejection] = []
    context = account_context
    if policy.max_quote_age_seconds is not None:
        captured_at = context.quote_captured_at if context else None
        if captured_at is None:
            rejections.append(
                RuleRejection("QUOTE_STALE", "no quote timestamp supplied")
            )
        else:
            age = (now - captured_at.astimezone(UTC)).total_seconds()
            if age < 0 or age > policy.max_quote_age_seconds:
                rejections.append(
                    RuleRejection(
                        "QUOTE_STALE", f"quote age {int(age)}s exceeds the limit"
                    )
                )
    if policy.require_quote_tradeable:
        tradeable = context.quote_tradeable if context else None
        if tradeable is not True:
            rejections.append(
                RuleRejection(
                    "NOT_TRADEABLE",
                    "the broker does not report the instrument as tradeable",
                )
            )
    return tuple(rejections)


def evaluate_entry_rules(
    intent: OrderIntent,
    *,
    policy: EntryRulePolicy,
    now: datetime,
    account_context: AccountExposureContext | None = None,
) -> tuple[RuleRejection, ...]:
    """Apply the entry rules in the guide's order and collect rejections.

    Closes (reduce-only, or a flat target) are exempt from every rule that
    guards new exposure but still must satisfy rule 3, exactly as
    PROJECT_GUIDE 5.7 specifies.
    """
    rejections = list(
        evaluate_quote_rules(
            intent, policy=policy, now=now, account_context=account_context
        )
    )
    if not _is_open_intent(intent):
        return tuple(rejections)

    context = account_context

    # Rule 7 — daily intent caps.
    if policy.max_daily_opens is not None:
        count = context.daily_open_count if context else None
        if count is None:
            rejections.append(
                RuleRejection("DAILY_INTENT_CAP", "today's open count is unknown")
            )
        elif count >= policy.max_daily_opens:
            rejections.append(
                RuleRejection(
                    "DAILY_INTENT_CAP",
                    f"{count} opens today already reached the cap",
                )
            )
    if policy.max_daily_symbol_opens is not None:
        count = context.daily_symbol_open_count if context else None
        if count is None:
            rejections.append(
                RuleRejection(
                    "DAILY_INTENT_CAP", "today's symbol open count is unknown"
                )
            )
        elif count >= policy.max_daily_symbol_opens:
            rejections.append(
                RuleRejection(
                    "DAILY_INTENT_CAP",
                    f"{count} opens today for {intent.symbol} reached the cap",
                )
            )

    # Rule 8 — maximum concurrent positions (opens only).
    if policy.max_open_positions is not None:
        open_positions = context.open_position_count if context else None
        if open_positions is None:
            rejections.append(
                RuleRejection("MAX_POSITIONS", "the open position count is unknown")
            )
        else:
            already_held = bool(
                context
                and intent.symbol in context.exposure_by_symbol
                and context.exposure_by_symbol[intent.symbol] > 0
            )
            if open_positions >= policy.max_open_positions and not already_held:
                rejections.append(
                    RuleRejection(
                        "MAX_POSITIONS",
                        f"{open_positions} positions already open",
                    )
                )

    # Rule 12 — losing-streak instrument freeze.
    if context is not None:
        reason = context.frozen_symbols.get(intent.symbol)
        if reason is not None:
            rejections.append(
                RuleRejection("LOSS_STREAK", f"{intent.symbol} is frozen: {reason}")
            )

    # Rule 6 — macro/news event window.
    if policy.event_window_minutes is not None:
        if context is None:
            rejections.append(
                RuleRejection(
                    "EVENT_WINDOW",
                    "no event-window context supplied",
                )
            )
        else:
            event_reason = context.recent_high_impact_events.get(intent.symbol)
            if event_reason is not None:
                rejections.append(
                    RuleRejection(
                        "EVENT_WINDOW",
                        f"high-impact event within {policy.event_window_minutes}m: "
                        f"{event_reason}",
                    )
                )

    # Rule 11 — soak drawdown state (3% blocks 48h, 5% halts the soak).
    if policy.block_on_drawdown:
        if context is None:
            rejections.append(
                RuleRejection(
                    "DRAWDOWN",
                    "no drawdown state supplied",
                )
            )
        elif context.drawdown_block_reason is not None:
            rejections.append(
                RuleRejection("DRAWDOWN", context.drawdown_block_reason)
            )

    # Rule 13 — Friday 13:00 UTC onward and weekends.
    if policy.block_weekend_and_late_friday:
        weekday = now.astimezone(UTC).weekday()
        if weekday >= 5:
            rejections.append(
                RuleRejection("WEEKEND", "the weekend does not open new exposure")
            )
        elif weekday == 4 and now.astimezone(UTC).hour >= FRIDAY_OPEN_CUTOFF_HOUR:
            rejections.append(
                RuleRejection(
                    "WEEKEND",
                    f"Friday from {FRIDAY_OPEN_CUTOFF_HOUR}:00 UTC is close-only",
                )
            )

    # Rule 14 — protective orders and a legal size.
    if policy.require_protective_orders:
        issues = _protective_order_issues(intent)
        if issues:
            rejections.append(RuleRejection("ORDER_INVALID", "; ".join(issues)))

    return tuple(rejections)


def rejection_codes(rejections: Sequence[RuleRejection]) -> tuple[str, ...]:
    """Return the distinct codes in order for a decision's tags."""
    return tuple(dict.fromkeys(rejection.code for rejection in rejections))


__all__ = [
    "FRIDAY_OPEN_CUTOFF_HOUR",
    "EntryRulePolicy",
    "RuleCode",
    "RuleRejection",
    "evaluate_entry_rules",
    "evaluate_quote_rules",
    "rejection_codes",
]
