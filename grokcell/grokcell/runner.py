"""python_tests runner. Not an MCP tool. Sets the fidelity bit bots cannot set."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .fidelity import FidelityRecord, FidelityStore
from .protocol import SUITE_BY_COMPONENT, WORLD_DIR

TEST_TIMEOUT_SECONDS = 30.0
UNSANDBOXED_RUNNER_ENV = "GROKCELL_ALLOW_UNSANDBOXED_RUNNER"


class RunOutcome(str, Enum):
    PASS = "pass"
    TESTS_FAILED = "tests_failed"
    INFRA_ERROR = "infra_error"
    TIMEOUT = "timeout"
    SANDBOX_REQUIRED = "sandbox_required"


@dataclass(frozen=True, slots=True)
class RunResult:
    outcome: RunOutcome
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def passed(self) -> bool:
        return self.outcome is RunOutcome.PASS


def _pytest_root() -> Path | None:
    spec = importlib.util.find_spec("pytest")
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).resolve().parent.parent


def _runner_environment(pytest_root: Path) -> dict[str, str]:
    allowed = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(
        {
            "PYTHONPATH": str(pytest_root),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        taskkill = system_root / "System32" / "taskkill.exe"
        if taskkill.is_file():
            try:
                subprocess.run(
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=5.0,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def suite_path(name: str) -> Path | None:
    relative = SUITE_BY_COMPONENT.get(name)
    if relative is None:
        return None
    path = WORLD_DIR / relative
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
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def current_suite_hash(name: str) -> str | None:
    path = suite_path(name)
    if path is None:
        return None
    return suite_hash(path)


def pytest_suite(
    path: Path,
    *,
    timeout: float = TEST_TIMEOUT_SECONDS,
    untrusted: bool = False,
) -> RunResult:
    if untrusted and os.environ.get(UNSANDBOXED_RUNNER_ENV) != "1":
        return RunResult(
            RunOutcome.SANDBOX_REQUIRED,
            4,
            stderr=(
                "generated Python is untrusted; execute it in an OS sandbox or set "
                f"{UNSANDBOXED_RUNNER_ENV}=1 only for trusted development inputs"
            ),
        )
    pytest_root = _pytest_root()
    if pytest_root is None:
        return RunResult(RunOutcome.INFRA_ERROR, 4, stderr="pytest is unavailable")
    ini = WORLD_DIR / "pytest.ini"
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(path),
        "-q",
        "--tb=no",
        "-p",
        "no:cacheprovider",
        "-c",
        str(ini),
        "--rootdir",
        str(path),
    ]
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_runner_environment(pytest_root),
            **kwargs,
        )
        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
            return RunResult(RunOutcome.TIMEOUT, -1)
        except BaseException:
            _terminate_process_tree(proc)
            raise
    except OSError as exc:
        return RunResult(RunOutcome.INFRA_ERROR, -1, stderr=str(exc))
    if exit_code == 0:
        outcome = RunOutcome.PASS
    elif exit_code == 1:
        outcome = RunOutcome.TESTS_FAILED
    else:
        outcome = RunOutcome.INFRA_ERROR
    return RunResult(outcome, int(exit_code))


def run_path(
    name: str,
    path: Path,
    *,
    store: FidelityStore | None = None,
    untrusted: bool = False,
) -> FidelityRecord:
    target = store if store is not None else FidelityStore.load()
    digest = suite_hash(path)
    proc = pytest_suite(path, untrusted=untrusted)
    record = FidelityRecord(
        name=name,
        passed=proc.passed,
        suite_hash=digest,
        exit_code=proc.exit_code,
        outcome=proc.outcome.value,
    )
    if proc.passed or not untrusted:
        target.put(record)
    return record


def run_component(name: str, *, store: FidelityStore | None = None) -> FidelityRecord:
    target = store if store is not None else FidelityStore.load()
    path = suite_path(name)
    if path is None:
        record = FidelityRecord(
            name=name,
            passed=False,
            suite_hash="",
            exit_code=4,
            outcome=RunOutcome.INFRA_ERROR.value,
        )
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
