"""Safe compiled strategy condition DSL (M12-W01).

StrategySpec conditions are compiled through a bounded typed AST that
cannot execute arbitrary Python, SQL, shell, template, import, or
attribute-access code. Imports, calls outside the indicator allowlist,
attribute traversal, comprehensions, mutation, file access, and other
forbidden syntax are rejected before evaluation. Evaluation is a pure
function of declared leaf inputs: identical versioned inputs produce
identical signals and undeclared future or external state is never read.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field

INDICATOR_ALLOWLIST: frozenset[str] = frozenset(
    {"ema", "sma", "rsi", "atr", "bb_upper", "bb_lower", "roc", "stdev"}
)
DATA_ALLOWLIST: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume"}
)

ComparisonOp = Literal["gt", "gte", "lt", "lte", "eq", "neq"]
LogicOp = Literal["and", "or"]


class _DslModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LiteralNode(_DslModel):
    kind: Literal["literal"] = "literal"
    value: float | int


class DataNode(_DslModel):
    kind: Literal["data"] = "data"
    name: str = Field(min_length=1)


class IndicatorNode(_DslModel):
    kind: Literal["indicator"] = "indicator"
    name: str = Field(min_length=1)
    parameters: list[Any] = Field(default_factory=list)

    def leaf_key(self) -> str:
        rendered = ",".join(
            str(p) if isinstance(p, str) else repr(p) for p in self.parameters
        )
        return f"{self.name}({rendered})"


class ComparisonNode(_DslModel):
    kind: Literal["comparison"] = "comparison"
    op: ComparisonOp
    left: IndicatorNode | DataNode | LiteralNode
    right: IndicatorNode | DataNode | LiteralNode


class LogicNode(_DslModel):
    kind: Literal["logic"] = "logic"
    op: LogicOp
    operands: list[ConditionExpr] = Field(min_length=2)


class NotNode(_DslModel):
    kind: Literal["not"] = "not"
    operand: ConditionExpr


ConditionExpr = ComparisonNode | LogicNode | NotNode


class StrategyCondition(_DslModel):
    """The compiled, normalized, typed condition."""

    source: str = Field(min_length=1)
    root: ConditionExpr
    requirements: list[str] = Field(default_factory=list)

    def normalized_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude={"source"}),
            sort_keys=True,
        )

    def leaf_keys(self) -> list[str]:
        """The declared leaf inputs (data names + indicator signatures)."""
        return sorted(self.requirements)


class DslCompileError(ValueError):
    """Raised when a condition cannot be compiled safely."""


class DslEvaluationError(ValueError):
    """Raised when evaluation reads undeclared or missing state."""


# ---------------------------------------------------------------------------
# Compiler: Python-expression grammar -> typed AST
# ---------------------------------------------------------------------------

_FORBIDDEN_PY_NODES: tuple[type[ast.AST], ...] = (
    ast.Attribute,
    ast.Subscript,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.Lambda,
    ast.Import,
    ast.ImportFrom,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.NamedExpr,
    ast.BinOp,
    ast.IfExp,
    ast.FormattedValue,
    ast.JoinedStr,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.Assign,
    ast.AugAssign,
    ast.Starred,
)

_COMPARE_OPS: dict[type[ast.cmpop], ComparisonOp] = {
    ast.Gt: "gt",
    ast.GtE: "gte",
    ast.Lt: "lt",
    ast.LtE: "lte",
    ast.Eq: "eq",
    ast.NotEq: "neq",
}


def _reject(node: ast.AST, reason: str) -> NoReturn:
    raise DslCompileError(
        f"forbidden syntax at line {getattr(node, 'lineno', '?')}: {reason}"
    )


def _convert_expr(node: ast.AST) -> IndicatorNode | DataNode | LiteralNode:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            _reject(node, "boolean literals are not supported")
        return LiteralNode(value=node.value)
    if isinstance(node, ast.Name):
        if node.id not in DATA_ALLOWLIST:
            _reject(node, f"undeclared data name {node.id!r}")
        return DataNode(name=node.id)
    if isinstance(node, ast.Call):
        func = node.func
        if not isinstance(func, ast.Name):
            _reject(node, "only simple indicator names may be called")
        if func.id not in INDICATOR_ALLOWLIST:
            _reject(node, f"indicator {func.id!r} is not in the allowlist")
        if node.keywords:
            _reject(node, "keyword arguments are not supported")
        parameters: list[Any] = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(
                arg.value, (int, float)
            ):
                parameters.append(arg.value)
            elif isinstance(arg, ast.Name):
                if arg.id not in DATA_ALLOWLIST:
                    _reject(arg, f"undeclared data name {arg.id!r}")
                parameters.append(arg.id)
            else:
                _reject(arg, "indicator parameters must be literals or data names")
        return IndicatorNode(name=func.id, parameters=parameters)
    _reject(node, f"unsupported expression {type(node).__name__}")
    raise AssertionError("unreachable")


def _convert_condition(node: ast.AST) -> ConditionExpr:
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            op: LogicOp = "and"
        elif isinstance(node.op, ast.Or):
            op = "or"
        else:
            _reject(node, "unsupported boolean operator")
        operands = [_convert_condition(value) for value in node.values]
        return LogicNode(op=op, operands=operands)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return NotNode(operand=_convert_condition(node.operand))
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            _reject(node, "chained comparisons are not supported")
        op_type = type(node.ops[0])
        if op_type not in _COMPARE_OPS:
            _reject(node, "unsupported comparison operator")
        left = _convert_expr(node.left)
        right = _convert_expr(node.comparators[0])
        return ComparisonNode(
            op=_COMPARE_OPS[op_type],
            left=left,
            right=right,
        )
    _reject(node, f"unsupported condition syntax {type(node).__name__}")
    raise AssertionError("unreachable")


def _walk(
    node: ConditionExpr | IndicatorNode | DataNode | LiteralNode, out: list[str]
) -> None:
    if isinstance(node, LogicNode):
        for operand in node.operands:
            _walk(operand, out)
    elif isinstance(node, NotNode):
        _walk(node.operand, out)
    elif isinstance(node, ComparisonNode):
        _walk(node.left, out)
        _walk(node.right, out)
    elif isinstance(node, IndicatorNode):
        out.append(node.leaf_key())
    elif isinstance(node, DataNode):
        out.append(node.name)


def compile_condition(source: str) -> StrategyCondition:
    """Parse, validate, and normalize one strategy condition safely."""
    normalized = source.strip()
    if not normalized:
        raise DslCompileError("condition must not be blank")
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise DslCompileError(f"invalid condition syntax: {exc}") from exc
    root_expr = tree.body

    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_PY_NODES):
            _reject(node, f"{type(node).__name__} is not allowed")

    root = _convert_condition(root_expr)
    requirements: list[str] = []
    _walk(root, requirements)
    deduplicated = list(dict.fromkeys(requirements))
    return StrategyCondition(
        source=normalized,
        root=root,
        requirements=deduplicated,
    )


# ---------------------------------------------------------------------------
# Evaluator: pure function over declared leaves only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationContext:
    """Declared leaf values; anything else is undeclared state."""

    values: Mapping[str, float | int]

    def resolve(self, key: str) -> float:
        if key not in self.values:
            raise DslEvaluationError(
                f"evaluation read undeclared or missing leaf {key!r}"
            )
        return float(self.values[key])


def _eval_expr(
    expr: IndicatorNode | DataNode | LiteralNode,
    context: EvaluationContext,
) -> float:
    if isinstance(expr, LiteralNode):
        return float(expr.value)
    return context.resolve(
        expr.leaf_key() if isinstance(expr, IndicatorNode) else expr.name
    )


def evaluate_condition(
    condition: StrategyCondition,
    leaf_values: Mapping[str, float | int],
) -> bool:
    """Evaluate the compiled condition purely over its declared leaves."""
    context = EvaluationContext(values=leaf_values)

    def _eval(node: ConditionExpr) -> bool:
        if isinstance(node, LogicNode):
            results = [_eval(operand) for operand in node.operands]
            return all(results) if node.op == "and" else any(results)
        if isinstance(node, NotNode):
            return not _eval(node.operand)
        left = _eval_expr(node.left, context)
        right = _eval_expr(node.right, context)
        if node.op == "gt":
            return left > right
        if node.op == "gte":
            return left >= right
        if node.op == "lt":
            return left < right
        if node.op == "lte":
            return left <= right
        if node.op == "eq":
            return left == right
        return left != right

    return _eval(condition.root)


__all__ = [
    "DATA_ALLOWLIST",
    "INDICATOR_ALLOWLIST",
    "ComparisonNode",
    "DataNode",
    "DslCompileError",
    "DslEvaluationError",
    "EvaluationContext",
    "IndicatorNode",
    "LiteralNode",
    "LogicNode",
    "NotNode",
    "StrategyCondition",
    "compile_condition",
    "evaluate_condition",
]
