"""python_tests runner. Not an MCP tool. Sets the fidelity bit bots cannot set."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .fidelity import FidelityRecord, FidelityStore
from .protocol import SUITE_BY_COMPONENT, WORLD_DIR

TEST_TIMEOUT_SECONDS = 30.0
UNSANDBOXED_RUNNER_ENV = "GROKCELL_ALLOW_UNSANDBOXED_RUNNER"
SANDBOX_IMAGE_ENV = "GROKCELL_SANDBOX_IMAGE"
DEADLINE_ENV = "GROKCELL_EXPERIMENT_DEADLINE"
MAX_OUTPUT_BYTES = 16_384


class RunOutcome(str, Enum):
    PASS = "pass"
    TESTS_FAILED = "tests_failed"
    INFRA_ERROR = "infra_error"
    TIMEOUT = "timeout"
    SANDBOX_REQUIRED = "sandbox_required"
    OUTPUT_LIMIT = "output_limit"
    CLEANUP_FAILED = "cleanup_failed"


@dataclass(frozen=True, slots=True)
class RunResult:
    outcome: RunOutcome
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    elapsed_ms: int = 0

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


def _capture(command: list[str], *, cwd: Path | None, env: dict[str, str] | None,
             timeout: float, sandbox_name: str | None = None,
             input_bytes: bytes | None = None) -> RunResult:
    """The outer process status is authoritative; output is bounded diagnostic data."""
    buffers = [bytearray(), bytearray()]
    truncated = [False, False]
    output_limit = threading.Event()

    def drain(stream, index: int) -> None:
        while chunk := stream.read(4096):
            available = MAX_OUTPUT_BYTES - len(buffers[index])
            if available > 0:
                buffers[index].extend(chunk[:available])
            if len(chunk) > available:
                truncated[index] = True
                output_limit.set()

    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            command, cwd=str(cwd) if cwd else None, env=env,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs,
        )
    except OSError as exc:
        return RunResult(RunOutcome.INFRA_ERROR, -1, stderr=str(exc))
    assert proc.stdout is not None and proc.stderr is not None
    readers = [threading.Thread(target=drain, args=(stream, index), daemon=True)
               for index, stream in enumerate((proc.stdout, proc.stderr))]
    for reader in readers:
        reader.start()
    writer = None
    if input_bytes is not None:
        def send() -> None:
            assert proc.stdin is not None
            try:
                proc.stdin.write(input_bytes)
                proc.stdin.close()
            except (OSError, BrokenPipeError):
                pass
        writer = threading.Thread(target=send, daemon=True)
        writer.start()
    deadline = started + timeout
    try:
        while proc.poll() is None and not output_limit.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                proc.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                pass
        if output_limit.is_set():
            _terminate_process_tree(proc)
            outcome, exit_code = RunOutcome.OUTPUT_LIMIT, -1
        elif proc.poll() is None:
            _terminate_process_tree(proc)
            outcome, exit_code = RunOutcome.TIMEOUT, -1
        else:
            exit_code = proc.returncode
            outcome = (RunOutcome.PASS if exit_code == 0 else
                       RunOutcome.TESTS_FAILED if exit_code == 1 else RunOutcome.INFRA_ERROR)
    finally:
        if sandbox_name:
            # Killing the Docker client does not guarantee its container stopped.
            try:
                subprocess.run(["docker", "rm", "-f", sandbox_name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5, check=False)
                check = subprocess.run(
                    ["docker", "ps", "-a", "--filter", f"name=^{sandbox_name}$",
                     "--format", "{{.Names}}"], capture_output=True, timeout=5,
                    check=False)
                if check.returncode != 0 or check.stdout.strip():
                    outcome = RunOutcome.CLEANUP_FAILED
                    buffers[1].extend(f"\nsandbox_cleanup_unverified:{sandbox_name}".encode())
            except (OSError, subprocess.TimeoutExpired):
                outcome = RunOutcome.CLEANUP_FAILED
                buffers[1].extend(f"\nsandbox_cleanup_unverified:{sandbox_name}".encode())
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
        for reader in readers:
            reader.join(timeout=1)
        if writer is not None:
            writer.join(timeout=1)
        for stream in (proc.stdout, proc.stderr):
            stream.close()
    if output_limit.is_set() and outcome is not RunOutcome.CLEANUP_FAILED:
        outcome = RunOutcome.OUTPUT_LIMIT
    return RunResult(
        outcome, exit_code,
        buffers[0].decode("utf-8", errors="replace"),
        buffers[1].decode("utf-8", errors="replace"),
        truncated[0], truncated[1],
        int((time.monotonic() - started) * 1000),
    )


def _sandbox_base(path: Path, image: str) -> tuple[list[str], str]:
    if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("sandbox image must be pinned by sha256 digest")
    name = "grokcell-" + uuid.uuid4().hex
    return ([
        "docker", "run", "--rm", "--name", name, "--pull=never",
        "--log-driver=none",
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=64",
        "--memory=512m", "--cpus=1", "--user=65534:65534",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=64m",
        "--mount", f"type=bind,source={path.resolve()},target=/workspace,readonly",
        "--workdir=/workspace", "--env=HOME=/tmp",
        "--env=PYTHONDONTWRITEBYTECODE=1",
        "--env=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
    ], name)


def _sandbox_command(path: Path, image: str) -> tuple[list[str], str]:
    base, name = _sandbox_base(path, image)
    return (base + ["--entrypoint=python", image, "-m", "pytest", "/workspace",
        "-q", "--tb=short", "-p", "no:cacheprovider",
        "--rootdir=/workspace",
    ], name)


_CALL_SCRIPT = """import importlib, json, sys
sys.path.insert(0, '/workspace')
item = json.load(sys.stdin)
args = None
try:
    if item['scope'] == 'component':
        module = importlib.import_module('service')
        fn = getattr(module, item['function'])
        args = item['args']
        value = fn(*args)
        result = {'type': 'return', 'value': value, 'args_after': args}
    elif item['scope'] == 'application':
        decoder = importlib.import_module('event_decoder').decode_event
        reducer = importlib.import_module('inventory_reducer').apply_event
        api = importlib.import_module('availability_api').availability
        state = {}
        for raw in item['raw_events']:
            state = reducer(state, decoder(raw))
        result = {'type': 'return', 'value': api(state, item['sku'])}
    else:
        raise ValueError('invalid scope')
except Exception as exc:
    result = {'type': 'exception', 'name': type(exc).__name__}
    if item.get('scope') == 'component' and args is not None:
        result['args_after'] = args
try:
    encoded = json.dumps({'completed': True, 'result': result}, separators=(',', ':'))
except (TypeError, ValueError):
    encoded = json.dumps({'completed': True, 'result': {'type': 'exception',
                          'name': 'UnserializableReturn'}})
print(encoded)
"""


def isolated_call(path: Path, payload: dict, *, timeout: float = 8.0) -> tuple[RunResult, dict | None]:
    """Return candidate behavior only; the host compares it with hidden expected data."""
    image = os.environ.get(SANDBOX_IMAGE_ENV)
    if not image:
        return RunResult(RunOutcome.SANDBOX_REQUIRED, 4), None
    try:
        base, name = _sandbox_base(path, image)
    except ValueError as exc:
        return RunResult(RunOutcome.INFRA_ERROR, 4, stderr=str(exc)), None
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 64_000:
        return RunResult(RunOutcome.INFRA_ERROR, 4, stderr="probe payload too large"), None
    command = base + ["-i", "--entrypoint=python", image, "-I", "-c", _CALL_SCRIPT]
    result = _capture(command, cwd=None, env=None, timeout=_bounded_timeout(timeout),
                      sandbox_name=name, input_bytes=encoded)
    if not result.passed or result.stdout_truncated or result.stderr_truncated:
        return result, None
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        return RunResult(RunOutcome.INFRA_ERROR, result.exit_code,
                         stderr="probe did not complete exactly once",
                         elapsed_ms=result.elapsed_ms), None
    try:
        report = json.loads(lines[0])
    except json.JSONDecodeError:
        report = None
    if not isinstance(report, dict) or report.get("completed") is not True or not isinstance(report.get("result"), dict):
        return RunResult(RunOutcome.INFRA_ERROR, result.exit_code,
                         stderr="invalid probe completion", elapsed_ms=result.elapsed_ms), None
    return result, report["result"]


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


def _bounded_timeout(requested: float) -> float:
    value = os.environ.get(DEADLINE_ENV)
    if not value:
        return requested
    try:
        return max(0.001, min(requested, float(value) - time.monotonic()))
    except ValueError:
        return 0.001


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
    image = os.environ.get(SANDBOX_IMAGE_ENV) if untrusted else None
    if image:
        try:
            command, name = _sandbox_command(path, image)
        except ValueError as exc:
            return RunResult(RunOutcome.INFRA_ERROR, 4, stderr=str(exc))
        # Docker is only a transport here. The pinned image must contain pytest.
        return _capture(command, cwd=None, env=None,
                        timeout=_bounded_timeout(timeout), sandbox_name=name)
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
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "-c",
        str(ini),
        "--rootdir",
        str(path),
    ]
    return _capture(command, cwd=path, env=_runner_environment(pytest_root),
                    timeout=timeout)


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
