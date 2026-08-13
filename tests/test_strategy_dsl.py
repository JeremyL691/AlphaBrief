"""M12-W01: safe compiled strategy condition DSL.

Covers AC-M12-W01-01/02/03: valid fixtures compile into a typed
normalized AST with deterministic serialization and explicit indicator,
operator, parameter, and data requirements; imports, calls outside the
allowlist, attribute traversal, comprehensions, mutation, file access,
SQL, templates, and shell syntax are rejected before evaluation;
evaluation over identical versioned inputs produces identical signals
and never reads undeclared future or external state.
"""

from __future__ import annotations

import pytest
from alphabrief_strategy import (
    ComparisonNode,
    DataNode,
    DslCompileError,
    DslEvaluationError,
    IndicatorNode,
    LiteralNode,
    LogicNode,
    NotNode,
    StrategyCondition,
    compile_condition,
    evaluate_condition,
)


class TestCompilation:
    def test_valid_fixture_compiles_to_typed_ast(self) -> None:
        condition = compile_condition(
            "ema(close, 20) > sma(close, 50) and not rsi(14) >= 70"
        )
        assert isinstance(condition, StrategyCondition)
        assert isinstance(condition.root, LogicNode)
        assert condition.root.op == "and"
        assert isinstance(condition.root.operands[0], ComparisonNode)
        assert isinstance(condition.root.operands[1], NotNode)
        comparison = condition.root.operands[0]
        assert isinstance(comparison.left, IndicatorNode)
        assert comparison.left.name == "ema"
        assert comparison.left.parameters == ["close", 20]
        assert comparison.op == "gt"
        assert isinstance(comparison.right, IndicatorNode)

    def test_literals_and_data_nodes(self) -> None:
        condition = compile_condition("close > 100")
        comparison = condition.root
        assert isinstance(comparison, ComparisonNode)
        assert isinstance(comparison.left, DataNode)
        assert comparison.left.name == "close"
        assert isinstance(comparison.right, LiteralNode)
        assert comparison.right.value == 100

    def test_normalized_serialization_is_deterministic(self) -> None:
        first = compile_condition("rsi(14) < 30 or ema(close, 10) > close")
        second = compile_condition("rsi(14) < 30 or ema(close, 10) > close")
        assert first.normalized_json() == second.normalized_json()
        assert first.normalized_json() == first.normalized_json()

    def test_requirements_are_explicit_and_deduplicated(self) -> None:
        condition = compile_condition(
            "ema(close, 20) > sma(close, 50) and ema(close, 20) < 2"
        )
        assert condition.requirements == [
            "ema(close,20)",
            "sma(close,50)",
        ]
        assert condition.leaf_keys() == condition.requirements

    def test_all_comparison_operators(self) -> None:
        for source, op in (
            ("close > volume", "gt"),
            ("close >= volume", "gte"),
            ("close < volume", "lt"),
            ("close <= volume", "lte"),
            ("close == volume", "eq"),
            ("close != volume", "neq"),
        ):
            condition = compile_condition(source)
            assert isinstance(condition.root, ComparisonNode)
            assert condition.root.op == op, source

    def test_blank_condition_rejected(self) -> None:
        with pytest.raises(DslCompileError):
            compile_condition("   ")


class TestRejectionMatrix:
    @pytest.mark.parametrize(
        "source",
        [
            "__import__('os').system('ls')",
            "import os",
            "from os import system",
            "open('/etc/passwd').read()",
            "a.attr > 1",
            "obj.method() > 1",
            "close[0] > 1",
            "close[1:2] > 1",
            "[x for x in close] > 1",
            "{x: 1 for x in close} > 1",
            "lambda: 1",
            "exec('x')",
            "eval('1')",
            "getattr(a, 'b') > 1",
            "not_an_indicator(close) > 1",
            "unknown_data > 1",
            "a + b > 1",
            "a * b > 1",
            "f'a{b}' > 1",
            "x := 1",
            "close and sma(close, 5) and rsi(14) and unknown",
        ],
    )
    def test_forbidden_syntax_rejected(self, source: str) -> None:
        with pytest.raises(DslCompileError):
            compile_condition(source)

    def test_attribute_traversal_rejected(self) -> None:
        with pytest.raises(DslCompileError, match="Attribute"):
            compile_condition("close.__class__ > 1")

    def test_subscript_rejected(self) -> None:
        with pytest.raises(DslCompileError, match="Subscript"):
            compile_condition("close[-1] > 1")

    def test_comprehension_rejected(self) -> None:
        with pytest.raises(DslCompileError, match="ListComp"):
            compile_condition("[x for x in close] > 1")

    def test_indicator_outside_allowlist_rejected(self) -> None:
        with pytest.raises(DslCompileError, match="allowlist"):
            compile_condition("mystery(close) > 1")

    def test_undeclared_data_rejected(self) -> None:
        with pytest.raises(DslCompileError, match="undeclared"):
            compile_condition("future_price > 1")

    def test_boolean_literal_rejected(self) -> None:
        with pytest.raises(DslCompileError):
            compile_condition("close > True")

    def test_keyword_arguments_rejected(self) -> None:
        with pytest.raises(DslCompileError):
            compile_condition("ema(close, period=20) > 1")


class TestEvaluation:
    def test_identical_inputs_produce_identical_signals(self) -> None:
        condition = compile_condition("rsi(14) < 30 and close > 100")
        values = {"rsi(14)": 25, "close": 120}
        assert evaluate_condition(condition, values) is True
        assert evaluate_condition(condition, values) is True
        assert evaluate_condition(condition, values) is True

    def test_boolean_semantics(self) -> None:
        condition = compile_condition(
            "close > 1 and (rsi(14) < 2 or volume == 3)"
        )
        assert evaluate_condition(
            condition, {"close": 2, "rsi(14)": 1, "volume": 9}
        ) is True
        assert evaluate_condition(
            condition, {"close": 2, "rsi(14)": 9, "volume": 9}
        ) is False
        assert evaluate_condition(
            condition, {"close": 2, "rsi(14)": 1, "volume": 3}
        ) is True

    def test_not_semantics(self) -> None:
        condition = compile_condition("not close > 100")
        assert evaluate_condition(condition, {"close": 90}) is True
        assert evaluate_condition(condition, {"close": 110}) is False
        assert evaluate_condition(condition, {"close": 100}) is True

    def test_undeclared_state_never_read(self) -> None:
        condition = compile_condition("close > 100")
        with pytest.raises(DslEvaluationError, match="undeclared"):
            evaluate_condition(condition, {})
        # An extra undeclared value is ignored: the condition only reads
        # its declared leaves.
        assert evaluate_condition(condition, {"close": 101, "extra": 1}) is True
        with pytest.raises(DslEvaluationError, match="undeclared"):
            evaluate_condition(condition, {"open": 5})
