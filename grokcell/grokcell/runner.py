"""python_tests runner. Not an MCP tool. Sets the fidelity bit bots cannot set."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from .fidelity import FidelityRecord, FidelityStore
from .protocol import PROJECT_ROOT, SUITE_BY_COMPONENT


def suite_path(name: str) -> Path | None:
    relative = SUITE_BY_COMPONENT.get(name)
    if relative is None:
        return None
    path = PROJECT_ROOT / relative
    if not path.is_dir():
        return None
    return path


def suite_hash(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and item.suffix == ".py" and item.name != "__pycache__"
    )
    for file in files:
        digest.update(str(file.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def current_suite_hash(name: str) -> str | None:
    path = suite_path(name)
    if path is None:
        return None
    return suite_hash(path)


def pytest_suite(path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    ini = PROJECT_ROOT / "world" / "pytest.ini"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(path),
            "-q",
            "--tb=no",
            "-c",
            str(ini),
            "--rootdir",
            str(path),
        ],
        cwd=str(path),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def run_path(name: str, path: Path, *, store: FidelityStore | None = None) -> FidelityRecord:
    target = store if store is not None else FidelityStore.load()
    digest = suite_hash(path)
    proc = pytest_suite(path)
    record = FidelityRecord(
        name=name,
        passed=proc.returncode == 0,
        suite_hash=digest,
        exit_code=int(proc.returncode),
    )
    target.put(record)
    return record


def run_component(name: str, *, store: FidelityStore | None = None) -> FidelityRecord:
    target = store if store is not None else FidelityStore.load()
    path = suite_path(name)
    if path is None:
        record = FidelityRecord(name=name, passed=False, suite_hash="", exit_code=2)
        target.put(record)
        return record
    return run_path(name, path, store=target)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m grokcell.runner <component>", file=sys.stderr)
        return 2
    record = run_component(args[0])
    print(json.dumps(record.to_json(), indent=2))
    return 0 if record.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
