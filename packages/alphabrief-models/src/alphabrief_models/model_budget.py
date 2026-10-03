"""Daily model-channel budget (PROJECT_GUIDE 5.13).

The budget is enforced against **recorded calls**, not against an
in-memory counter, so a restart cannot hand the system a fresh
allowance:

* ``chatgpt_plan`` — at most ``DEFAULT_CHATGPT_DAILY_CALLS`` calls per UTC
  day (configurable);
* ``openai_compatible`` — at most ``DEFAULT_FALLBACK_DAILY_USD`` of
  estimated cost per UTC day;
* any channel that answered with a rate limit or a quota error is
  disabled for the rest of the UTC day, so the runtime records
  ``NO_TRADE_MODEL_UNAVAILABLE`` instead of hammering a channel that has
  already said no.

The guard reads usage through a small :class:`ModelUsageSource` protocol
so the models package never imports the API application (the durable
implementation lives in ``alphabrief_api.db.model_call``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol, cast

#: Channel identifiers as recorded on model-call rows.
CHATGPT_PLAN_CHANNEL = "chatgpt_plan"
OPENAI_COMPATIBLE_CHANNEL = "openai_compatible"

#: Reason codes the runtime records when a round cannot call a model.
NO_TRADE_MODEL_BUDGET = "NO_TRADE_MODEL_BUDGET"
NO_TRADE_MODEL_UNAVAILABLE = "NO_TRADE_MODEL_UNAVAILABLE"

#: Default limits from PROJECT_GUIDE 5.13.
DEFAULT_CHATGPT_DAILY_CALLS = 150
DEFAULT_FALLBACK_DAILY_USD = Decimal("2.00")
MAX_COMMITTEE_NORMAL_CALLS = 5
MAX_COMMITTEE_REPAIR_CALLS = 2
#: The single-call shadow baseline (PROJECT_GUIDE 5.11) is one manager call
#: per symbol per round. It is a third kind: it never borrows a normal or a
#: repair slot, but it counts toward the round total and the daily budget, so
#: it only runs when the round still has budget left.
MAX_SHADOW_CALLS_PER_SYMBOL = 1
MAX_ROUND_CALLS = 35
ModelCallKind = Literal["normal", "repair", "shadow"]


@dataclass(frozen=True)
class ChannelUsage:
    """One channel's recorded usage for a UTC day."""

    calls: int = 0
    cost: Decimal = Decimal("0")
    cost_known: bool = True


@dataclass(frozen=True)
class ModelBudgetPolicy:
    """Per-channel daily limits; a channel without a limit is unlimited."""

    daily_call_limits: Mapping[str, int] = field(
        default_factory=lambda: {CHATGPT_PLAN_CHANNEL: DEFAULT_CHATGPT_DAILY_CALLS}
    )
    daily_cost_limits: Mapping[str, Decimal] = field(
        default_factory=lambda: {OPENAI_COMPATIBLE_CHANNEL: DEFAULT_FALLBACK_DAILY_USD}
    )

    def __post_init__(self) -> None:
        for channel, call_limit in self.daily_call_limits.items():
            if (
                isinstance(call_limit, bool)
                or not isinstance(call_limit, int)
                or call_limit <= 0
            ):
                raise ValueError(f"daily call limit for {channel!r} must be positive")
        for channel, cost_limit in self.daily_cost_limits.items():
            if (
                not isinstance(cost_limit, Decimal)
                or not cost_limit.is_finite()
                or cost_limit <= 0
            ):
                raise ValueError(f"daily cost limit for {channel!r} must be positive")

    @classmethod
    def default(cls) -> ModelBudgetPolicy:
        return cls()

    def call_limit(self, channel: str) -> int | None:
        return self.daily_call_limits.get(channel)

    def cost_limit(self, channel: str) -> Decimal | None:
        return self.daily_cost_limits.get(channel)


@dataclass(frozen=True)
class BudgetVerdict:
    """One deterministic budget verdict for a channel."""

    allowed: bool
    channel: str
    reason: str
    detail: str
    calls_today: int = 0
    cost_today: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, str | bool | int]:
        return {
            "allowed": self.allowed,
            "channel": self.channel,
            "reason": self.reason,
            "detail": self.detail,
            "calls_today": self.calls_today,
            "cost_today": str(self.cost_today),
        }


class ModelUsageSource(Protocol):
    """Durable usage/state source the guard reads (implemented by the store)."""

    def daily_usage(self, since: datetime) -> Mapping[str, ChannelUsage]: ...

    def disabled_channel_reason(self, channel: str, day: str) -> str | None: ...

    def disable_channel(self, channel: str, day: str, reason: str) -> None: ...


class ModelBudgetGuard:
    """Enforce the per-channel daily budget against recorded usage."""

    def __init__(
        self,
        usage: ModelUsageSource,
        *,
        policy: ModelBudgetPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._usage = usage
        self._policy = policy or ModelBudgetPolicy.default()
        self._clock = clock or (lambda: datetime.now(UTC))

    def admit(self, channel: str) -> BudgetVerdict:
        """Return whether one more call on ``channel`` is allowed now."""
        now = self._clock().astimezone(UTC)
        day = now.date().isoformat()
        disabled_reason = self._usage.disabled_channel_reason(channel, day)
        if disabled_reason is not None:
            return BudgetVerdict(
                allowed=False,
                channel=channel,
                reason=NO_TRADE_MODEL_UNAVAILABLE,
                detail=f"{channel} is disabled for {day}: {disabled_reason}",
            )
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        usage = self._usage.daily_usage(since).get(channel, ChannelUsage())
        call_limit = self._policy.call_limit(channel)
        if call_limit is not None and usage.calls >= call_limit:
            return BudgetVerdict(
                allowed=False,
                channel=channel,
                reason=NO_TRADE_MODEL_BUDGET,
                detail=(f"{channel} used {usage.calls} of {call_limit} daily calls"),
                calls_today=usage.calls,
                cost_today=usage.cost,
            )
        cost_limit = self._policy.cost_limit(channel)
        if cost_limit is not None and not usage.cost_known:
            return BudgetVerdict(
                False, channel, NO_TRADE_MODEL_BUDGET, "paid usage has no cost evidence"
            )
        if cost_limit is not None and usage.cost >= cost_limit:
            return BudgetVerdict(
                allowed=False,
                channel=channel,
                reason=NO_TRADE_MODEL_BUDGET,
                detail=(f"{channel} spent {usage.cost} of {cost_limit} USD today"),
                calls_today=usage.calls,
                cost_today=usage.cost,
            )
        return BudgetVerdict(
            allowed=True,
            channel=channel,
            reason="",
            detail=(
                f"{channel}: {usage.calls} calls"
                + (f", {usage.cost} USD" if usage.cost else "")
                + " today"
            ),
            calls_today=usage.calls,
            cost_today=usage.cost,
        )

    def record_channel_unavailable(self, channel: str, *, detail: str) -> None:
        """Disable a channel for the rest of the UTC day (rate limit/quota)."""
        now = self._clock().astimezone(UTC)
        self._usage.disable_channel(channel, now.date().isoformat(), detail)

    def reserve(
        self,
        channel: str,
        call_id: str,
        *,
        estimated_cost: Decimal | None = None,
        round_key: str | None = None,
        symbol: str | None = None,
        call_kind: ModelCallKind = "normal",
    ) -> BudgetVerdict:
        """Persist admission before dispatch; an unknown outcome keeps its slot."""
        try:
            source = cast(ModelAdmissionSource, self._usage)
            return source.reserve_call(
                channel=channel,
                call_id=call_id,
                observed_at=self._clock().astimezone(UTC),
                call_limit=self._policy.call_limit(channel),
                cost_limit=self._policy.cost_limit(channel),
                estimated_cost=estimated_cost,
                round_key=round_key,
                symbol=symbol,
                call_kind=call_kind,
            )
        except Exception:
            return BudgetVerdict(
                False,
                channel,
                NO_TRADE_MODEL_BUDGET,
                "durable model admission unavailable",
            )

    def cost_limited(self, channel: str) -> bool:
        return self._policy.cost_limit(channel) is not None


class ModelAdmissionSource(ModelUsageSource, Protocol):
    def reserve_call(
        self,
        *,
        channel: str,
        call_id: str,
        observed_at: datetime,
        call_limit: int | None,
        cost_limit: Decimal | None,
        estimated_cost: Decimal | None,
        round_key: str | None = None,
        symbol: str | None = None,
        call_kind: ModelCallKind = "normal",
    ) -> BudgetVerdict: ...


__all__ = [
    "CHATGPT_PLAN_CHANNEL",
    "DEFAULT_CHATGPT_DAILY_CALLS",
    "DEFAULT_FALLBACK_DAILY_USD",
    "NO_TRADE_MODEL_BUDGET",
    "NO_TRADE_MODEL_UNAVAILABLE",
    "OPENAI_COMPATIBLE_CHANNEL",
    "BudgetVerdict",
    "ChannelUsage",
    "ModelBudgetGuard",
    "ModelBudgetPolicy",
    "ModelUsageSource",
]
