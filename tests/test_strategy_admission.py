"""M12-W02: machine-enforced strategy-family admission.

Covers AC-M12-W02-02/03: applicability is enforced by OANDA instrument
category and unsupported combinations fail admission with explicit
reasons; no-trade is first-class and admissible everywhere; predictive
or learned outputs (Kronos/Gym) are rejected as advisory-only and can
never be admitted as executable strategies.
"""

from __future__ import annotations

from typing import cast

import pytest
from alphabrief_strategy import (
    FAMILY_APPLICABILITY,
    PREDICTIVE_FAMILY_IDS,
    AdmissionResult,
    StrategyInstrumentCategory,
    evaluate_strategy_admission,
)

_ALL_CATEGORIES: tuple[StrategyInstrumentCategory, ...] = (
    "CURRENCY",
    "METAL",
    "INDEX_CFD",
    "COMMODITY_CFD",
    "BOND_CFD",
    "EQUITY_CFD",
    "CRYPTO_CFD",
    "OTHER_CFD",
)

#: Known family with a deliberately unsupported category per family.
_REJECTED_COMBINATIONS = (
    ("trend", "OTHER_CFD"),
    ("mean_reversion", "CRYPTO_CFD"),
    ("mean_reversion", "BOND_CFD"),
    ("breakout", "BOND_CFD"),
    ("breakout", "EQUITY_CFD"),
    ("volatility_regime", "CRYPTO_CFD"),
    ("volatility_regime", "BOND_CFD"),
)


def _approved_combinations() -> list[tuple[str, str]]:
    return [
        (family_id, category)
        for family_id, categories in FAMILY_APPLICABILITY.items()
        for category in _ALL_CATEGORIES
        if category in categories
    ]


class TestApprovedAdmission:
    @pytest.mark.parametrize("family_id,category", _approved_combinations())
    def test_applicable_combination_is_approved(
        self, family_id: str, category: str
    ) -> None:
        result = evaluate_strategy_admission(
            family_id, cast(StrategyInstrumentCategory, category)
        )
        assert result.decision == "approved"
        assert family_id in result.reason
        assert category in result.reason

    @pytest.mark.parametrize("category", _ALL_CATEGORIES)
    def test_no_trade_is_first_class_benchmark_for_every_category(
        self, category: str
    ) -> None:
        result = evaluate_strategy_admission(
            "no_trade", cast(StrategyInstrumentCategory, category)
        )
        assert result.decision == "approved"
        assert "no_trade" in result.reason


class TestRejectedAdmission:
    @pytest.mark.parametrize("family_id,category", _REJECTED_COMBINATIONS)
    def test_unsupported_combination_is_rejected_with_explicit_reason(
        self, family_id: str, category: str
    ) -> None:
        result = evaluate_strategy_admission(
            family_id, cast(StrategyInstrumentCategory, category)
        )
        assert result.decision == "rejected"
        assert family_id in result.reason
        assert category in result.reason
        assert "not applicable" in result.reason

    def test_unknown_family_is_rejected_with_unknown_reason(self) -> None:
        result = evaluate_strategy_admission("quantum_ai", "CURRENCY")
        assert result.decision == "rejected"
        assert "unknown strategy family" in result.reason
        assert "quantum_ai" in result.reason

    @pytest.mark.parametrize("family_id", sorted(PREDICTIVE_FAMILY_IDS))
    def test_predictive_families_are_rejected_as_advisory_only(
        self, family_id: str
    ) -> None:
        for category in _ALL_CATEGORIES:
            result = evaluate_strategy_admission(family_id, category)
            assert result.decision == "rejected"
            assert "advisory" in result.reason
            assert family_id in result.reason

    def test_predictive_families_are_never_admissible_for_any_category(
        self,
    ) -> None:
        for family_id in PREDICTIVE_FAMILY_IDS:
            assert family_id not in FAMILY_APPLICABILITY


class TestAdmissionContract:
    def test_verdict_is_a_pure_function_of_its_inputs(self) -> None:
        first = evaluate_strategy_admission("breakout", "CRYPTO_CFD")
        second = evaluate_strategy_admission("breakout", "CRYPTO_CFD")
        assert first.model_dump() == second.model_dump()

    def test_verdict_is_typed_and_reason_is_explicit(self) -> None:
        result = evaluate_strategy_admission("trend", "CURRENCY")
        assert isinstance(result, AdmissionResult)
        assert result.decision in ("approved", "rejected")
        assert result.reason.strip() != ""
        assert result.family_id == "trend"
        assert result.instrument_category == "CURRENCY"

    def test_every_family_is_registered(self) -> None:
        assert set(FAMILY_APPLICABILITY) == {
            "trend",
            "mean_reversion",
            "breakout",
            "volatility_regime",
            "no_trade",
        }
