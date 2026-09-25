"""Keep generated experiment modules in the small pure-Python task language.

Docker is the host isolation boundary. This additional gate prevents candidate
modules from controlling the pytest/probe interpreter that measures them.
"""
from __future__ import annotations

import ast

_BUILTIN_CALLS = {"ValueError", "TypeError", "abs", "bool", "dict", "enumerate", "int", "isinstance",
                  "len", "list", "max", "min", "range", "set", "sorted",
                  "str", "sum", "tuple", "type", "zip"}
_METHOD_CALLS = {"append", "copy", "get", "items", "keys", "lower", "pop",
                 "setdefault", "strip", "update", "upper", "values"}
_FORBIDDEN_NODES = (ast.AsyncFunctionDef, ast.Await, ast.ClassDef, ast.Delete,
                    ast.Global, ast.ImportFrom, ast.Lambda, ast.Nonlocal,
                    ast.Yield, ast.YieldFrom)


def validate_module(source: str) -> None:
    if len(source.encode("utf-8")) > 50_000:
        raise ValueError("candidate_source_too_large")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError("candidate_syntax_invalid") from exc
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            if any(alias.name != "json" or alias.asname for alias in statement.names):
                raise ValueError("candidate_import_forbidden")
        elif isinstance(statement, (ast.FunctionDef, ast.Expr)):
            if isinstance(statement, ast.FunctionDef) and statement.decorator_list:
                raise ValueError("candidate_decorator_forbidden")
            if isinstance(statement, ast.Expr) and not isinstance(statement.value, ast.Constant):
                raise ValueError("candidate_top_level_effect")
        else:
            raise ValueError("candidate_top_level_effect")
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            raise ValueError("candidate_construct_forbidden")
        if isinstance(node, ast.Import) and node not in tree.body:
            raise ValueError("candidate_import_forbidden")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("candidate_reflection_forbidden")
        if isinstance(node, ast.Name) and node.id.startswith("_") and node.id != "_":
            raise ValueError("candidate_reflection_forbidden")
        if isinstance(node, ast.Name) and node.id in {"SystemExit", "KeyboardInterrupt", "BaseException"}:
            raise ValueError("candidate_control_flow_forbidden")
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                if fn.id not in _BUILTIN_CALLS and fn.id not in {
                        item.name for item in tree.body if isinstance(item, ast.FunctionDef)}:
                    raise ValueError("candidate_call_forbidden")
            elif isinstance(fn, ast.Attribute):
                if not ((isinstance(fn.value, ast.Name) and fn.value.id == "json"
                         and fn.attr in {"loads", "dumps"}) or fn.attr in _METHOD_CALLS):
                    raise ValueError("candidate_call_forbidden")
            else:
                raise ValueError("candidate_call_forbidden")
