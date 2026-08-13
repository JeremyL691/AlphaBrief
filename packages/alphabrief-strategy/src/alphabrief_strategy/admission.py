"""Machine-enforced strategy-family admission (M12-W02).

Admission is a deterministic pure function of ``(family_id,
instrument_category)``: unsupported combinations are rejected with an
explicit reason before any signal is generated. Predictive or learned
outputs (Kronos/Gym) can never be admitted as executable strategies;
they remain advisory evidence only (REQ-STRAT-007).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_strategy.families import (
    FAMILY_APPLICABILITY,
    StrategyInstrumentCategory,
)

AdmissionDecision = Literal["approved", "rejected"]

#: Family ids that produce predictive or learned outputs. These are
#: advisory evidence only and are never admissible as executable
#: strategies (REQ-STRAT-007).
PREDICTIVE_FAMILY_IDS: frozenset[str] = frozenset(
    {"kronos_forecast", "gym_policy"}
)

_ADVISORY_REASON = (
    "predictive or learned outputs are advisory evidence only and cannot "
    "be admitted as an executable strategy"
)


class AdmissionResult(BaseModel):
    """One deterministic family-by-category admission verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family_id: str = Field(min_length=1)
    instrument_category: StrategyInstrumentCategory
    decision: AdmissionDecision
    reason: str = Field(min_length=1)

    @field_validator("family_id", "reason")
    @classmethod
    def strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("admission strings must not be blank")
        return value


def evaluate_strategy_admission(
    family_id: str,
    instrument_category: StrategyInstrumentCategory,
) -> AdmissionResult:
    """Admit or reject one ``(family_id, category)`` combination.

    The verdict is a pure function of its two inputs: identical inputs
    always produce identical verdicts and reasons.
    """
    if family_id in FAMILY_APPLICABILITY:
        if instrument_category in FAMILY_APPLICABILITY[family_id]:
            return AdmissionResult(
                family_id=family_id,
                instrument_category=instrument_category,
                decision="approved",
                reason=(
                    f"{family_id} is applicable to OANDA instrument "
                    f"category {instrument_category}"
                ),
            )
        return AdmissionResult(
            family_id=family_id,
            instrument_category=instrument_category,
            decision="rejected",
            reason=(
                f"{family_id} is not applicable to OANDA instrument "
                f"category {instrument_category}"
            ),
        )
    if family_id in PREDICTIVE_FAMILY_IDS:
        return AdmissionResult(
            family_id=family_id,
            instrument_category=instrument_category,
            decision="rejected",
            reason=f"{family_id}: {_ADVISORY_REASON}",
        )
    return AdmissionResult(
        family_id=family_id,
        instrument_category=instrument_category,
        decision="rejected",
        reason=f"unknown strategy family {family_id!r}",
    )


__all__ = [
    "PREDICTIVE_FAMILY_IDS",
    "AdmissionDecision",
    "AdmissionResult",
    "evaluate_strategy_admission",
]
