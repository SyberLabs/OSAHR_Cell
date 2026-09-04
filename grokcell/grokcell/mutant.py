"""AST mutants of the module. The suite must kill them. Not confirmatory."""
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

from .artifact import python_files
from .runner import pytest_suite


def _implementation_files(path: Path) -> list[Path]:
    return [
        item
        for item in python_files(path)
        if not item.name.startswith("test_") and item.name != "conftest.py"
    ]


class _FlipReturnConstants(ast.NodeTransformer):
    def __init__(self) -> None:
        self.flipped = False

    def visit_Return(self, node: ast.Return) -> ast.Return:
        if self.flipped or node.value is None:
            return node
        value = node.value
        if isinstance(value, ast.Constant):
            if isinstance(value.value, str) and value.value:
                self.flipped = True
                node.value = ast.Constant(value=value.value + "!")
            elif isinstance(value.value, bool):
                self.flipped = True
                node.value = ast.Constant(value=not value.value)
            elif isinstance(value.value, (int, float)) and value.value != 0:
                self.flipped = True
                node.value = ast.Constant(value=type(value.value)(0))
        return node


def mutate_source(source: str) -> str | None:
    tree = ast.parse(source)
    transformer = _FlipReturnConstants()
    mutated = transformer.visit(tree)
    if not transformer.flipped:
        return None
    ast.fix_missing_locations(mutated)
    return ast.unparse(mutated) + "\n"


def kill_mutant(path: Path) -> tuple[bool, str]:
    targets = _implementation_files(path)
    if not targets:
        return False, "mutant_untestable"
    original = targets[0].read_text(encoding="utf-8")
    mutated = mutate_source(original)
    if mutated is None:
        return False, "mutant_untestable"
    with tempfile.TemporaryDirectory(prefix="grokcell-mutant-") as raw:
        dest = Path(raw)
        for item in python_files(path):
            relative = item.relative_to(path)
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if item == targets[0]:
                target.write_text(mutated, encoding="utf-8")
            else:
                target.write_bytes(item.read_bytes())
        proc = pytest_suite(dest)
        if proc.returncode == 0:
            return False, "mutant_survived"
        return True, "mutant_killed"
