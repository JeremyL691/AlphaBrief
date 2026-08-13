"""M11-W04: bounded, explainable daily candidate selection.

Covers AC-M11-W04-01/02/03: selection never exceeds configured
instrument, per-category, model-call, token, cost, or concurrency
budgets; every selected and skipped instrument records deterministic
rule results; equivalent inputs produce the same ordered candidate set
while the complete catalogue stays queryable.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from alphabrief_trader.candidate_selection import (
    CandidateBudgets,
    DailyCandidateSelector,
    InstrumentFacts,
)
from pydantic import ValidationError


def _facts(
    symbol: str, category: str = "CURRENCY", **overrides: object
) -> InstrumentFacts:
    base: dict[str, object] = {
        "symbol": symbol,
        "category": category,
        "catalog_active": True,
        "quote_fresh": True,
        "tradeable": True,
        "spread_pct": Decimal("0.0005"),
        "liquidity": Decimal("100"),
        "data_quality_ok": True,
        "news_relevance": Decimal("0.5"),
        "estimated_model_calls": 10,
        "estimated_tokens": 1000,
        "estimated_cost": Decimal("0.01"),
    }
    base.update(overrides)
    return InstrumentFacts(**cast(Any, base))


def _budgets(**overrides: object) -> CandidateBudgets:
    base: dict[str, object] = {
        "max_instruments": 20,
        "max_per_category": 5,
        "max_model_calls": 200,
        "max_tokens": 100_000,
        "max_cost": Decimal("1.00"),
        "max_concurrency": 4,
    }
    base.update(overrides)
    return CandidateBudgets(**cast(Any, base))


SELECTOR = DailyCandidateSelector()


class TestBudgetEnforcement:
    def test_instrument_budget_never_exceeded(self) -> None:
        instruments = [_facts(f"X{i:02d}") for i in range(10)]
        result = SELECTOR.select(instruments, _budgets(max_instruments=3))
        assert len(result.candidates) == 3
        assert result.usage.instrument_count == 3
        skipped = [v for v in result.verdicts if not v.selected]
        assert any(
            r.rule == "instrument_budget" for v in skipped for r in v.rule_results
        )

    def test_per_category_budget_never_exceeded(self) -> None:
        instruments = [
            _facts(f"X{i:02d}", category="CURRENCY") for i in range(4)
        ] + [_facts(f"Y{i:02d}", category="METAL") for i in range(4)]
        result = SELECTOR.select(instruments, _budgets(max_per_category=2))
        assert result.usage.per_category["CURRENCY"] == 2
        assert result.usage.per_category["METAL"] == 2
        assert len(result.candidates) == 4

    def test_model_call_budget_never_exceeded(self) -> None:
        instruments = [
            _facts(f"X{i:02d}", estimated_model_calls=10) for i in range(10)
        ]
        result = SELECTOR.select(instruments, _budgets(max_model_calls=25))
        assert result.usage.model_calls <= 25
        assert len(result.candidates) == 2
        assert any(
            r.rule == "model_call_budget"
            for v in result.verdicts
            for r in v.rule_results
        )

    def test_token_budget_never_exceeded(self) -> None:
        instruments = [
            _facts(f"X{i:02d}", estimated_tokens=1000) for i in range(10)
        ]
        result = SELECTOR.select(instruments, _budgets(max_tokens=2500))
        assert result.usage.tokens <= 2500
        assert len(result.candidates) == 2

    def test_cost_budget_never_exceeded(self) -> None:
        instruments = [
            _facts(f"X{i:02d}", estimated_cost=Decimal("0.40")) for i in range(10)
        ]
        result = SELECTOR.select(instruments, _budgets(max_cost=Decimal("1.00")))
        assert result.usage.cost <= Decimal("1.00")
        assert len(result.candidates) == 2

    def test_concurrency_budget_never_exceeded(self) -> None:
        instruments = [_facts(f"X{i:02d}") for i in range(10)]
        result = SELECTOR.select(instruments, _budgets(max_concurrency=2))
        assert result.usage.instrument_count <= 2
        assert any(
            r.rule == "concurrency_budget"
            for v in result.verdicts
            for r in v.rule_results
        )

    def test_float_budget_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _budgets(max_cost=1.0)


class TestExplainableRules:
    def test_selected_instrument_records_all_rules(self) -> None:
        result = SELECTOR.select([_facts("EUR_USD")], _budgets())
        verdict = result.verdicts[0]
        assert verdict.selected is True
        rules = {r.rule: r.passed for r in verdict.rule_results}
        assert set(rules) == {
            "catalogue_status",
            "category",
            "quote_freshness",
            "tradeability",
            "spread",
            "liquidity",
            "data_quality",
            "news_relevance",
        }
        assert all(rules.values())

    def test_inactive_catalogue_skipped_with_reason(self) -> None:
        result = SELECTOR.select(
            [_facts("EUR_USD", catalog_active=False)], _budgets()
        )
        verdict = result.verdicts[0]
        assert verdict.selected is False
        assert verdict.selection_reason == "skipped: catalogue_status"
        rule = next(r for r in verdict.rule_results if r.rule == "catalogue_status")
        assert rule.passed is False
        assert rule.detail == "inactive"

    def test_stale_quote_skipped_with_reason(self) -> None:
        result = SELECTOR.select([_facts("EUR_USD", quote_fresh=False)], _budgets())
        verdict = result.verdicts[0]
        assert verdict.selected is False
        assert verdict.selection_reason == "skipped: quote_freshness"

    def test_wide_spread_skipped(self) -> None:
        result = SELECTOR.select(
            [_facts("EUR_USD", spread_pct=Decimal("0.005"))], _budgets()
        )
        assert result.verdicts[0].selected is False
        rule = next(
            r for r in result.verdicts[0].rule_results if r.rule == "spread"
        )
        assert rule.passed is False

    def test_low_liquidity_skipped(self) -> None:
        result = SELECTOR.select(
            [_facts("EUR_USD", liquidity=Decimal("0.5"))], _budgets()
        )
        assert result.verdicts[0].selected is False

    def test_unacceptable_data_quality_skipped(self) -> None:
        result = SELECTOR.select(
            [_facts("EUR_USD", data_quality_ok=False)], _budgets()
        )
        assert result.verdicts[0].selected is False
        assert result.verdicts[0].selection_reason == "skipped: data_quality"

    def test_low_news_relevance_skipped(self) -> None:
        selector = DailyCandidateSelector(news_relevance_threshold=Decimal("0.8"))
        result = selector.select(
            [_facts("EUR_USD", news_relevance=Decimal("0.5"))], _budgets()
        )
        assert result.verdicts[0].selected is False
        assert result.verdicts[0].selection_reason == "skipped: news_relevance"

    def test_unknown_category_skipped(self) -> None:
        result = SELECTOR.select(
            [_facts("EXOTIC1", category="unknown")], _budgets()
        )
        assert result.verdicts[0].selected is False
        assert result.verdicts[0].selection_reason == "skipped: category"


class TestDeterminismAndCompleteness:
    def test_equivalent_inputs_produce_same_ordered_candidates(self) -> None:
        instruments = [_facts(f"X{i:02d}") for i in range(5)]
        first = SELECTOR.select(instruments, _budgets())
        second = SELECTOR.select(list(reversed(instruments)), _budgets())
        assert first.candidates == second.candidates
        assert [v.symbol for v in first.verdicts] == [
            v.symbol for v in second.verdicts
        ]

    def test_candidates_are_category_ordered(self) -> None:
        instruments = [
            _facts("B2", category="METAL"),
            _facts("A1", category="CURRENCY"),
            _facts("C3", category="CFD"),
        ]
        result = SELECTOR.select(instruments, _budgets())
        # Deterministic order: category, then symbol (CFD < CURRENCY < METAL
        # alphabetically).
        assert result.candidates == ["C3", "A1", "B2"]

    def test_complete_catalogue_stays_queryable(self) -> None:
        instruments = [
            _facts("EUR_USD"),
            _facts("XAU_USD", category="METAL"),
            _facts("UK100", category="CFD", catalog_active=False),
        ]
        result = SELECTOR.select(instruments, _budgets())
        # The verdicts cover the full catalogue even when skipped.
        assert {v.symbol for v in result.verdicts} == {
            "EUR_USD",
            "XAU_USD",
            "UK100",
        }
        assert len(result.verdicts) == 3
