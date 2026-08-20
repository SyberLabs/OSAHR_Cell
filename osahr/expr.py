"""Restricted, deterministic expression evaluator used by guards and hazards."""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import ExpressionError


_ALLOWED_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
    "bool": bool,
    "len": len,
    "sum": sum,
    "exp": math.exp,
    "log": math.log,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tanh": math.tanh,
    "floor": math.floor,
    "ceil": math.ceil,
    "isfinite": math.isfinite,
    "clip": lambda value, lower, upper: min(max(value, lower), upper),
    "softplus": lambda value: value if value > 40.0 else math.log1p(math.exp(value)),
}

_ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.Subscript,
    ast.Tuple,
    ast.List,
    ast.Dict,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Slice,
)


class Namespace(Mapping[str, Any]):
    """Read-only mapping that supports both item and attribute access."""

    def __init__(self, data: Mapping[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        value = self._data[key]
        return Namespace(value) if isinstance(value, Mapping) else value

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


class _Validator(ast.NodeVisitor):
    def visit(self, node: ast.AST) -> Any:
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"Disallowed expression node: {type(node).__name__}")
        return super().visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            raise ExpressionError("Dunder names are forbidden")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise ExpressionError("Private attributes are forbidden")
        self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS:
            raise ExpressionError("Only whitelisted pure functions may be called")
        if any(keyword.arg is None for keyword in node.keywords):
            raise ExpressionError("Argument unpacking is forbidden")
        for child in (*node.args, *node.keywords):
            self.visit(child.value if isinstance(child, ast.keyword) else child)


@dataclass(frozen=True, slots=True)
class Expr:
    source: str
    _code: Any = field(init=False, repr=False, compare=False, metadata={"canonical": False})
    _names: frozenset[str] = field(init=False, repr=False, compare=False, metadata={"canonical": False})

    def __post_init__(self) -> None:
        try:
            tree = ast.parse(self.source, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(f"Invalid expression {self.source!r}") from exc
        _Validator().visit(tree)
        object.__setattr__(self, "_code", compile(tree, "<osahr-expr>", "eval"))
        object.__setattr__(self, "_names", frozenset(
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        ))

    @property
    def names(self) -> frozenset[str]:
        return self._names

    def __reduce__(self):
        return (Expr, (self.source,))

    def evaluate(self, context: Mapping[str, Any]) -> Any:
        safe_locals = {name: Namespace(value) if isinstance(value, Mapping) else value for name, value in context.items()}
        safe_globals = {"__builtins__": {}, **_ALLOWED_FUNCTIONS}
        try:
            return eval(self._code, safe_globals, safe_locals)
        except Exception as exc:
            raise ExpressionError(f"Expression failed: {self.source!r}: {exc}") from exc


def evaluate_value(value: Any, context: Mapping[str, Any]) -> Any:
    return value.evaluate(context) if isinstance(value, Expr) else value


def get_path(root: Mapping[str, Any], path: str) -> Any:
    current: Any = root
    for segment in path.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            raise ExpressionError(f"Unknown path {path!r}")
        current = current[segment]
    return current


def set_path(root: dict[str, Any], path: str, value: Any) -> None:
    segments = path.split(".")
    if not segments or any(not segment for segment in segments):
        raise ExpressionError(f"Invalid path {path!r}")
    current = root
    for segment in segments[:-1]:
        existing = current.get(segment)
        if existing is None:
            existing = {}
            current[segment] = existing
        if not isinstance(existing, dict):
            raise ExpressionError(f"Cannot descend through non-mapping path segment {segment!r}")
        current = existing
    current[segments[-1]] = value
