"""Operator-owned example contracts. Candidates supply behavior, never verdicts."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from ..repair_guard import validate_module
from .ports import CheckContract
from .records import Candidate, CheckResult, JsonSnapshot, canonical, digest

# Public demonstration contract, not a sealed benchmark or universal proof.
REPAIR_CASES = (
    ("difference", [12, 5], {"type": "return", "value": 7}),
    ("zero", [0, 0], {"type": "return", "value": 0}),
    ("fully_reserved", [8, 8], {"type": "return", "value": 0}),
    ("over_reserved", [2, 3], {"type": "exception", "name": "ValueError"}),
    ("negative", [-1, 0], {"type": "exception", "name": "ValueError"}),
    ("boolean", [True, 0], {"type": "exception", "name": "ValueError"}),
    ("string", ["10", 2], {"type": "exception", "name": "ValueError"}),
)


def snapshot_directory(root: Path, *, maximum_files=256, maximum_bytes=4_194_304) -> JsonSnapshot:
    """Conservative identity includes non-Python assets; never follows symlinks.

    This captures a snapshot identity, not a live subscription to filesystem
    changes. A caller using a mutable workspace must recheck before admission.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("regular snapshot directory required")
    files, used = {}, 0
    paths = []
    for path in root.rglob("*"):
        if len(paths) >= maximum_files * 4:
            raise ValueError("snapshot entry limit")
        paths.append(path)
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError("snapshot symlinks are not supported")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("snapshot special files are not supported")
        if len(files) >= maximum_files:
            raise ValueError("snapshot file limit")
        with path.open("rb") as handle:
            raw = handle.read(maximum_bytes - used + 1)
        used += len(raw)
        if used > maximum_bytes:
            raise ValueError("snapshot byte limit")
        files[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    return JsonSnapshot.capture({"files": files})


def validate_arithmetic_component(source: str) -> None:
    """Demo-specific language contract prevents mutation of the probe interpreter.

    The shared legacy guard is retained, then narrowed: no imports, attributes,
    helper functions, defaults or loops. Only type(x) and ValueError(x) calls.
    This is a bounded component language, not a claim to sandbox all of Python.
    """
    validate_module(source)
    tree = ast.parse(source)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "available":
        raise ValueError("one available function required")
    fn = functions[0]
    if (len(fn.args.args) != 2 or fn.args.posonlyargs or fn.args.kwonlyargs or fn.args.vararg
            or fn.args.kwarg or fn.args.defaults or fn.args.kw_defaults):
        raise ValueError("two positional arguments without defaults required")
    allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Expr, ast.Constant,
               ast.Return, ast.If, ast.Raise, ast.Assign, ast.Name, ast.Load, ast.Store,
               ast.Compare, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Call, ast.IfExp,
               ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd, ast.Add, ast.Sub, ast.Mult,
               ast.Div, ast.FloorDiv, ast.Mod, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
               ast.GtE, ast.Is, ast.IsNot)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError("outside bounded arithmetic component language")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name)
                or node.func.id not in {"type", "ValueError"} or len(node.args) != 1 or node.keywords):
            raise ValueError("only type(x) and ValueError(x) calls are permitted")


class IsolatedRepairVerifier:
    mode = "isolated"

    def __init__(self, image: str):
        if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
            raise ValueError("digest-pinned image required")
        if shutil.which("docker") is None:
            raise RuntimeError("Docker unavailable; no host execution fallback")
        self.image = image
        package = Path(__file__).resolve().parents[1]
        binding = {name: hashlib.sha256((package / name).read_bytes()).hexdigest()
                   for name in ("runner.py", "repair_guard.py", "execution/checking.py")}
        self.contract = CheckContract("inventory-availability:" + digest(list(REPAIR_CASES_JSON())),
                                      "host-oracle:" + digest(binding), image,
                                      ("language", *(item[0] for item in REPAIR_CASES)))

    def verify(self, candidate: Candidate):
        from ..runner import RunOutcome, isolated_call
        if os.environ.get("GROKCELL_SANDBOX_IMAGE") != self.image:
            raise RuntimeError("configured executor changed")
        if candidate.artifact_type != "python_component":
            raise ValueError("repair verifier requires a Python component")
        try:
            validate_arithmetic_component(candidate.content.decode("utf-8"))
        except (ValueError, UnicodeError):
            return (CheckResult("language", "fail"),
                    *(CheckResult(name, "unknown") for name, _, _ in REPAIR_CASES))
        results = [CheckResult("language", "pass")]
        deadline = time.monotonic() + 30
        with tempfile.TemporaryDirectory(prefix="grokcell-execution-check-") as raw:
            path = Path(raw)
            path.chmod(0o755)  # The sandbox runs as uid 65534, not the host owner.
            (path / "service.py").write_bytes(candidate.content)
            (path / "service.py").chmod(0o444)
            for name, args, expected in REPAIR_CASES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    results.append(CheckResult(name, "unknown"))
                    continue
                run, actual = isolated_call(path, {"scope": "component", "function": "available", "args": args},
                                            timeout=min(3, remaining))
                if not run.passed or actual is None:
                    status = "fail" if run.outcome is RunOutcome.TESTS_FAILED else "unknown"
                else:
                    # Host decides each verdict using host-owned expected data.
                    status = "pass" if (all(canonical(actual.get(key)) == canonical(value) for key, value in expected.items())
                                            and canonical(actual.get("args_after")) == canonical(args)) else "fail"
                results.append(CheckResult(name, status))
            if (path / "service.py").read_bytes() != candidate.content:
                raise RuntimeError("candidate bytes changed during checking")
        return tuple(results)


def REPAIR_CASES_JSON():
    return [[name, args, expected] for name, args, expected in REPAIR_CASES]


class DependencyVerifier:
    """Checks exact supplied facts and lack of upgrade authority, not prose truth."""
    mode = "data_only"

    def __init__(self, source: JsonSnapshot):
        self.source = source
        self.contract = CheckContract("dependency-facts:" + source.identity,
                                      "dependency-checker:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                      "stdlib-json", ("schema", "snapshot_facts", "no_upgrade_authority", "human_review"))

    def verify(self, candidate: Candidate):
        if candidate.artifact_type != "dependency_assessment":
            raise ValueError("dependency assessment artifact required")
        try:
            data = json.loads(candidate.content)
            if canonical(data) != candidate.content:
                data = None
        except (ValueError, UnicodeError, TypeError):
            data = None
        source = self.source.value()
        schema = type(data) is dict and set(data) == {"dependency", "from_version", "to_version", "source_hash",
                                                     "compatibility", "review_required", "upgrade_authorized"}
        facts = schema and all(data.get(key) == value for key, value in {
            "dependency": source["dependency"], "from_version": source["from_version"],
            "to_version": source["to_version"], "source_hash": self.source.identity}.items())
        denial = type(data) is dict and data.get("upgrade_authorized") is False
        review = (type(data) is dict and data.get("review_required") is True
                  and data.get("compatibility") == "not_established")
        return tuple(CheckResult(name, "pass" if passed else "fail") for name, passed in (
            ("schema", schema), ("snapshot_facts", facts), ("no_upgrade_authority", denial), ("human_review", review)))
