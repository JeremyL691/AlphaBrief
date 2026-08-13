"""M11-W04: candidate selection budget accounting.

Covers AC-M11-W04-01 in detail: cumulative budget usage is tracked and
never exceeds the configured limits, and every budget exhaustion is
recorded as an explicit skipped verdict.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from alphabrief_trader.candidate_selection import (
    CandidateBudgets,
    DailyCandidateSelector,
    InstrumentFacts,
)

SELECTOR = DailyCandidateSelector()


def _facts(symbol: str, **overrides: object) -> InstrumentFacts:
    base: dict[str, object] = {
        "symbol": symbol,
        "category": "CURRENCY",
        "spread_pct": Decimal("0.0005"),
        "liquidity": Decimal("100"),
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


class TestBudgetAccounting:
    def test_usage_accumulates_only_for_selected(self) -> None:
        result = SELECTOR.select(
            [_facts("A1"), _facts("B1", catalog_active=False), _facts("C1")],
            _budgets(),
        )
        assert result.usage.instrument_count == 2
        assert result.usage.model_calls == 20
        assert result.usage.tokens == 2000
        assert result.usage.cost == Decimal("0.02")
        assert result.usage.per_category["CURRENCY"] == 2

    def test_budget_exhaustion_skips_remainder_deterministically(self) -> None:
        instruments = [_facts(f"X{i:02d}") for i in range(10)]
        result = SELECTOR.select(instruments, _budgets(max_concurrency=1))
        assert result.candidates == ["X00"]
        # Every subsequent instrument has an explicit concurrency verdict.
        for verdict in result.verdicts[1:]:
            assert verdict.selected is False
            assert any(
                r.rule == "concurrency_budget" for r in verdict.rule_results
            )

    def test_usage_reflects_all_selected_after_partial_budget(self) -> None:
        instruments = [
            _facts(f"X{i:02d}", estimated_cost=Decimal("0.30"))
            for i in range(10)
        ]
        result = SELECTOR.select(instruments, _budgets(max_cost=Decimal("1.00")))
        assert result.candidates == ["X00", "X01", "X02"]
        assert result.usage.cost == Decimal("0.90")
        assert result.usage.instrument_count == 3

    def test_zero_budget_selects_nothing(self) -> None:
        result = SELECTOR.select(
            [_facts("X00")], _budgets(max_model_calls=5)
        )
        assert result.candidates == []
        assert result.usage.model_calls == 0
        assert result.verdicts[0].selection_reason == "skipped: model_call_budget"

    def test_budget_fields_are_positive(self) -> None:
        budgets = _budgets()
        assert budgets.max_instruments >= 1
        assert budgets.max_per_category >= 1
        assert budgets.max_model_calls >= 1
        assert budgets.max_tokens >= 1
        assert budgets.max_cost >= 0
        assert budgets.max_concurrency >= 1
