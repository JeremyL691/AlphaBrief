"""External request deadlines, retry budgets, and concurrency limits
(M15-W03).

Every external request family — OANDA REST, OANDA stream,
market-data, content, model, alert, and backup — has a configured
connect, read, total, and cycle budget with bounded attempts and
jittered backoff. OANDA reconnect behavior respects official rate and
connection limits; unknown submit outcomes enter query and
reconciliation instead of blind retry. A timed-out provider task is
classified with complete scrubbed telemetry and never blocks
heartbeat, reconciliation, backup, risk freeze, or unrelated scheduled
work (REQ-OPS-003, REQ-OPS-005).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_core.alerting import classify_error
from alphabrief_core.observability import redact_observable

RequestFamily = Literal[
    "oanda_rest",
    "oanda_stream",
    "market_data",
    "content",
    "model",
    "alert",
    "backup",
]

REQUEST_FAMILIES: tuple[str, ...] = (
    "oanda_rest",
    "oanda_stream",
    "market_data",
    "content",
    "model",
    "alert",
    "backup",
)


class RequestBudget(BaseModel):
    """One configured external request budget."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family: RequestFamily
    connect_timeout_s: Decimal = Field(gt=0)
    read_timeout_s: Decimal = Field(gt=0)
    total_timeout_s: Decimal = Field(gt=0)
    cycle_budget_s: Decimal = Field(gt=0)
    max_attempts: int = Field(ge=1)
    backoff_base_s: Decimal = Field(ge=0)
    backoff_jitter: bool = True
    max_concurrency: int = Field(ge=1)


#: The single configured budget per external request family.
REQUEST_BUDGETS: dict[str, RequestBudget] = {
    "oanda_rest": RequestBudget(
        family="oanda_rest",
        connect_timeout_s=Decimal("10"),
        read_timeout_s=Decimal("30"),
        total_timeout_s=Decimal("60"),
        cycle_budget_s=Decimal("60"),
        max_attempts=3,
        backoff_base_s=Decimal("1"),
        backoff_jitter=True,
        max_concurrency=1,
    ),
    "oanda_stream": RequestBudget(
        family="oanda_stream",
        connect_timeout_s=Decimal("10"),
        read_timeout_s=Decimal("120"),
        total_timeout_s=Decimal("120"),
        cycle_budget_s=Decimal("60"),
        max_attempts=5,
        backoff_base_s=Decimal("2"),
        backoff_jitter=True,
        max_concurrency=1,
    ),
    "market_data": RequestBudget(
        family="market_data",
        connect_timeout_s=Decimal("10"),
        read_timeout_s=Decimal("30"),
        total_timeout_s=Decimal("60"),
        cycle_budget_s=Decimal("60"),
        max_attempts=3,
        backoff_base_s=Decimal("1"),
        backoff_jitter=True,
        max_concurrency=4,
    ),
    "content": RequestBudget(
        family="content",
        connect_timeout_s=Decimal("10"),
        read_timeout_s=Decimal("30"),
        total_timeout_s=Decimal("90"),
        cycle_budget_s=Decimal("120"),
        max_attempts=2,
        backoff_base_s=Decimal("1"),
        backoff_jitter=True,
        max_concurrency=4,
    ),
    "model": RequestBudget(
        family="model",
        connect_timeout_s=Decimal("10"),
        read_timeout_s=Decimal("120"),
        total_timeout_s=Decimal("180"),
        cycle_budget_s=Decimal("120"),
        max_attempts=2,
        backoff_base_s=Decimal("1"),
        backoff_jitter=True,
        max_concurrency=2,
    ),
    "alert": RequestBudget(
        family="alert",
        connect_timeout_s=Decimal("5"),
        read_timeout_s=Decimal("10"),
        total_timeout_s=Decimal("15"),
        cycle_budget_s=Decimal("30"),
        max_attempts=1,
        backoff_base_s=Decimal("0"),
        backoff_jitter=False,
        max_concurrency=1,
    ),
    "backup": RequestBudget(
        family="backup",
        connect_timeout_s=Decimal("10"),
        read_timeout_s=Decimal("60"),
        total_timeout_s=Decimal("120"),
        cycle_budget_s=Decimal("300"),
        max_attempts=2,
        backoff_base_s=Decimal("2"),
        backoff_jitter=True,
        max_concurrency=1,
    ),
}


def budget_for(family: str) -> RequestBudget:
    """The configured budget for one request family."""
    if family not in REQUEST_BUDGETS:
        raise KeyError(f"no budget configured for family {family!r}")
    return REQUEST_BUDGETS[family]


def backoff_seconds(
    budget: RequestBudget,
    attempt: int,
    *,
    seed: str = "",
) -> Decimal:
    """Deterministic jittered backoff for one bounded attempt.

    ``attempt`` is 1-based; attempts beyond ``max_attempts`` are
    rejected. Jitter is deterministic per (budget, attempt, seed):
    ``base * (1 + hash % 100 / 100)``.
    """
    if attempt < 1 or attempt > budget.max_attempts:
        raise ValueError(
            f"attempt {attempt} out of bounds [1, {budget.max_attempts}]"
        )
    if budget.backoff_base_s == 0:
        return Decimal("0")
    if not budget.backoff_jitter:
        return budget.backoff_base_s
    digest = hashlib.sha256(
        f"{budget.family}:{attempt}:{seed}".encode()
    ).hexdigest()
    jitter = Decimal(int(digest[:4], 16) % 100) / Decimal("100")
    return budget.backoff_base_s * (Decimal("1") + jitter)


def retry_allowed(
    budget: RequestBudget,
    attempt: int,
    error_code: str,
) -> bool:
    """Whether one failed attempt may retry.

    Retries are bounded by ``max_attempts`` and only allowed for
    retryable error classes (REQ-OPS-003).
    """
    if attempt >= budget.max_attempts:
        return False
    return classify_error(error_code).retryable


SubmitOutcome = Literal["accepted", "rejected", "unknown", "timeout"]


def submit_outcome_action(outcome: SubmitOutcome) -> str:
    """The deterministic action for one submit outcome.

    Unknown and timed-out submit outcomes enter query and
    reconciliation — never blind retry (REQ-OPS-005).
    """
    if outcome in ("accepted", "rejected"):
        return "recorded"
    return "query_and_reconcile"


class TimeoutTelemetry(BaseModel):
    """One complete scrubbed timeout classification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: str = Field(min_length=1)
    family: str = Field(min_length=1)
    elapsed_s: Decimal = Field(ge=0)
    budget_total_s: Decimal = Field(gt=0)
    classification: str = Field(min_length=1)
    fields: dict[str, str] = Field(default_factory=dict)


def classify_timeout(
    *,
    task: str,
    family: str,
    elapsed_s: Decimal,
    fields: dict[str, Any] | None = None,
) -> TimeoutTelemetry:
    """Classify one timed-out provider task with scrubbed telemetry.

    The classification is complete: every field value is scrubbed via
    the observability redaction contract.
    """
    budget = budget_for(family)
    return TimeoutTelemetry(
        task=task,
        family=family,
        elapsed_s=elapsed_s,
        budget_total_s=budget.total_timeout_s,
        classification="timeout",
        fields={
            key: redact_observable(str(value))
            for key, value in (fields or {}).items()
        },
    )


__all__ = [
    "REQUEST_BUDGETS",
    "REQUEST_FAMILIES",
    "RequestBudget",
    "RequestFamily",
    "SubmitOutcome",
    "TimeoutTelemetry",
    "backoff_seconds",
    "budget_for",
    "classify_timeout",
    "retry_allowed",
    "submit_outcome_action",
]
