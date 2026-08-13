"""Bounded, explainable daily candidate selection (M11-W04).

Selects a category-aware daily analysis set from the complete OANDA
catalogue using deterministic rules over catalogue status, category,
quote freshness, tradeability, spread, liquidity, data quality, and news
relevance, while never exceeding configured instrument, per-category,
model-call, token, cost, or concurrency budgets. Every instrument —
selected or skipped — records the full rule-result set, and equivalent
inputs produce the same ordered candidate set while the complete
catalogue remains queryable outside the analysis set.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_trader.schemas import _reject_float


class CandidateBudgets(BaseModel):
    """Configured limits for one daily analysis selection."""

    model_config = ConfigDict(extra="forbid")

    max_instruments: int = Field(default=20, ge=1)
    max_per_category: int = Field(default=5, ge=1)
    max_model_calls: int = Field(default=200, ge=1)
    max_tokens: int = Field(default=100_000, ge=1)
    max_cost: Decimal = Field(default=Decimal("1.00"), ge=0)
    max_concurrency: int = Field(default=4, ge=1)

    @field_validator("max_cost", mode="before")
    @classmethod
    def _no_float(cls, value: object) -> object:
        return _reject_float(value)


class InstrumentFacts(BaseModel):
    """One instrument's deterministic selection evidence."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    category: str = Field(min_length=1)
    catalog_active: bool = True
    quote_fresh: bool = True
    tradeable: bool = True
    spread_pct: Decimal = Field(default=Decimal("0"), ge=0)
    liquidity: Decimal = Field(default=Decimal("0"), ge=0)
    data_quality_ok: bool = True
    news_relevance: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    estimated_model_calls: int = Field(default=10, ge=1)
    estimated_tokens: int = Field(default=1000, ge=0)
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator(
        "spread_pct", "liquidity", "news_relevance", "estimated_cost", mode="before"
    )
    @classmethod
    def _no_float(cls, value: object) -> object:
        return _reject_float(value)


class CandidateRuleResult(BaseModel):
    """One deterministic rule result for one instrument."""

    model_config = ConfigDict(extra="forbid")

    rule: str = Field(min_length=1)
    passed: bool
    detail: str = Field(min_length=1)


class CandidateVerdict(BaseModel):
    """The full deterministic verdict for one instrument."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    category: str = Field(min_length=1)
    selected: bool
    selection_reason: str = Field(min_length=1)
    rule_results: list[CandidateRuleResult] = Field(default_factory=list)


class BudgetUsage(BaseModel):
    """Cumulative budget consumption of the selected set."""

    model_config = ConfigDict(extra="forbid")

    instrument_count: int = 0
    per_category: dict[str, int] = Field(default_factory=dict)
    model_calls: int = 0
    tokens: int = 0
    cost: Decimal = Decimal("0")


class CandidateSelectionResult(BaseModel):
    """The complete selection output: candidates, verdicts, usage."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[str] = Field(default_factory=list)
    verdicts: list[CandidateVerdict] = Field(default_factory=list)
    usage: BudgetUsage
    budgets: CandidateBudgets


class DailyCandidateSelector:
    """Stateless deterministic selector; identical inputs yield one result."""

    def __init__(
        self,
        *,
        max_spread_pct: Decimal = Decimal("0.0020"),
        min_liquidity: Decimal = Decimal("1"),
        news_relevance_threshold: Decimal = Decimal("0.0"),
    ) -> None:
        self._max_spread_pct = max_spread_pct
        self._min_liquidity = min_liquidity
        self._news_relevance_threshold = news_relevance_threshold

    def select(
        self,
        instruments: list[InstrumentFacts],
        budgets: CandidateBudgets,
    ) -> CandidateSelectionResult:
        """Select the ordered daily analysis set within every budget."""
        usage = BudgetUsage(
            per_category={},
            cost=Decimal("0"),
        )
        candidates: list[str] = []
        verdicts: list[CandidateVerdict] = []

        for facts in sorted(instruments, key=lambda f: (f.category, f.symbol)):
            rules: list[CandidateRuleResult] = []

            rules.append(
                CandidateRuleResult(
                    rule="catalogue_status",
                    passed=facts.catalog_active,
                    detail="active" if facts.catalog_active else "inactive",
                )
            )
            rules.append(
                CandidateRuleResult(
                    rule="category",
                    passed=facts.category.strip() not in {"", "unknown"},
                    detail=facts.category or "unknown",
                )
            )
            rules.append(
                CandidateRuleResult(
                    rule="quote_freshness",
                    passed=facts.quote_fresh,
                    detail="fresh" if facts.quote_fresh else "stale",
                )
            )
            rules.append(
                CandidateRuleResult(
                    rule="tradeability",
                    passed=facts.tradeable,
                    detail="tradeable" if facts.tradeable else "not_tradeable",
                )
            )
            rules.append(
                CandidateRuleResult(
                    rule="spread",
                    passed=facts.spread_pct <= self._max_spread_pct,
                    detail=f"spread_pct={facts.spread_pct}",
                )
            )
            rules.append(
                CandidateRuleResult(
                    rule="liquidity",
                    passed=facts.liquidity >= self._min_liquidity,
                    detail=f"liquidity={facts.liquidity}",
                )
            )
            rules.append(
                CandidateRuleResult(
                    rule="data_quality",
                    passed=facts.data_quality_ok,
                    detail="ok" if facts.data_quality_ok else "unacceptable",
                )
            )
            rules.append(
                CandidateRuleResult(
                    rule="news_relevance",
                    passed=facts.news_relevance >= self._news_relevance_threshold,
                    detail=f"relevance={facts.news_relevance}",
                )
            )

            eligibility_failures = [
                result for result in rules if not result.passed
            ]
            budget_failures: list[CandidateRuleResult] = []

            if not eligibility_failures:
                per_category = usage.per_category.get(facts.category, 0)
                if per_category >= budgets.max_per_category:
                    budget_failures.append(
                        CandidateRuleResult(
                            rule="per_category_budget",
                            passed=False,
                            detail=(
                                f"category={facts.category} at limit "
                                f"{budgets.max_per_category}"
                            ),
                        )
                    )
                if len(candidates) >= budgets.max_instruments:
                    budget_failures.append(
                        CandidateRuleResult(
                            rule="instrument_budget",
                            passed=False,
                            detail=f"at limit {budgets.max_instruments}",
                        )
                    )
                if (
                    usage.model_calls + facts.estimated_model_calls
                    > budgets.max_model_calls
                ):
                    budget_failures.append(
                        CandidateRuleResult(
                            rule="model_call_budget",
                            passed=False,
                            detail=(
                                "calls "
                                f"{usage.model_calls}+{facts.estimated_model_calls}"
                                f" > {budgets.max_model_calls}"
                            ),
                        )
                    )
                if usage.tokens + facts.estimated_tokens > budgets.max_tokens:
                    budget_failures.append(
                        CandidateRuleResult(
                            rule="token_budget",
                            passed=False,
                            detail=(
                                f"tokens {usage.tokens}+{facts.estimated_tokens}"
                                f" > {budgets.max_tokens}"
                            ),
                        )
                    )
                if usage.cost + facts.estimated_cost > budgets.max_cost:
                    budget_failures.append(
                        CandidateRuleResult(
                            rule="cost_budget",
                            passed=False,
                            detail=(
                                f"cost {usage.cost}+{facts.estimated_cost}"
                                f" > {budgets.max_cost}"
                            ),
                        )
                    )
                if len(candidates) >= budgets.max_concurrency:
                    budget_failures.append(
                        CandidateRuleResult(
                            rule="concurrency_budget",
                            passed=False,
                            detail=f"concurrency at limit {budgets.max_concurrency}",
                        )
                    )

            all_failures = eligibility_failures + budget_failures
            selected = not all_failures
            if selected:
                candidates.append(facts.symbol)
                usage.instrument_count += 1
                usage.per_category[facts.category] = (
                    usage.per_category.get(facts.category, 0) + 1
                )
                usage.model_calls += facts.estimated_model_calls
                usage.tokens += facts.estimated_tokens
                usage.cost += facts.estimated_cost

            verdicts.append(
                CandidateVerdict(
                    symbol=facts.symbol,
                    category=facts.category,
                    selected=selected,
                    selection_reason=(
                        "selected"
                        if selected
                        else f"skipped: {all_failures[0].rule}"
                    ),
                    rule_results=rules + budget_failures,
                )
            )

        return CandidateSelectionResult(
            candidates=candidates,
            verdicts=verdicts,
            usage=usage,
            budgets=budgets,
        )


__all__ = [
    "BudgetUsage",
    "CandidateBudgets",
    "CandidateRuleResult",
    "CandidateSelectionResult",
    "CandidateVerdict",
    "DailyCandidateSelector",
    "InstrumentFacts",
]
