"""Verifier and supervisor checks; generated candidate code never runs on the host."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from grokcell.execution import checking
from grokcell.execution.checking import DependencyVerifier, IsolatedRepairVerifier
from grokcell.execution.records import Candidate, JsonSnapshot, canonical
from grokcell.execution.workflows import REPAIRED_COMPONENT
import grokcell.runner as runner
from grokcell.runner import RunOutcome, RunResult

IMAGE = "example/python@sha256:" + "a" * 64
APPROVED_IMAGE_ENV = "GROKCELL_APPROVED_ISOLATION_TEST_IMAGE"


def _candidate(content: bytes, artifact_type="python_component"):
    return Candidate(artifact_type, content, "dependency-snapshot", 0, "s03-test")


def _verifier(monkeypatch):
    monkeypatch.setattr(checking.shutil, "which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setenv(runner.SANDBOX_IMAGE_ENV, IMAGE)
    return IsolatedRepairVerifier(IMAGE)


def _actual_for(args, cases):
    expected = next(item[2] for item in cases if canonical(item[1]) == canonical(args))
    return dict(expected) | {"args_after": args}


def test_isolated_verifier_requires_docker_without_host_fallback(monkeypatch):
    monkeypatch.setattr(checking.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="Docker unavailable"):
        IsolatedRepairVerifier(IMAGE)


def test_docker_command_has_digest_and_explicit_execution_limits(tmp_path):
    command, _name = runner._sandbox_command(tmp_path, IMAGE)

    assert command[:2] == ["docker", "run"]
    assert "--pull=never" in command
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
    assert "--user=65534:65534" in command
    assert "--pids-limit=64" in command
    assert "--memory=512m" in command
    assert "--memory-swap=512m" in command
    assert "--cpus=1" in command
    assert any(item.endswith(",readonly") and "target=/workspace" in item for item in command)
    assert IMAGE in command
    assert "--privileged" not in command
    assert not any("docker.sock" in item.lower() for item in command)


@pytest.mark.parametrize("source", [
    b"def available(on_hand, reserved):\n    raise SystemExit(0)\n",
    b"def available(on_hand, reserved):\n    print('{\"completed\":true}')\n    return 7\n",
    b"import os\nos._exit(0)\n",
])
def test_guard_rejects_early_exit_and_forged_output_before_runner(monkeypatch, source):
    verifier = _verifier(monkeypatch)
    monkeypatch.setattr(runner, "isolated_call",
                        lambda *_args, **_kwargs: pytest.fail("rejected candidate reached executor"))

    results = verifier.verify(_candidate(source))

    assert tuple(item.id for item in results) == verifier.contract.required
    assert results[0].id == "language" and results[0].status == "fail"
    assert all(item.status == "unknown" for item in results[1:])


def test_zero_exit_and_completion_marker_do_not_override_host_oracle(monkeypatch):
    verifier = _verifier(monkeypatch)
    cases = checking.REPAIR_CASES_JSON()
    calls = []

    def fake_capture(command, **kwargs):
        payload = json.loads(kwargs["input_bytes"])
        actual = _actual_for(payload["args"], cases)
        if canonical(payload["args"]) == canonical([12, 5]):
            actual["value"] = 999
        calls.append((command, kwargs))
        report = json.dumps({"completed": True, "result": actual}, separators=(",", ":")) + "\n"
        return RunResult(RunOutcome.PASS, 0, stdout=report)

    monkeypatch.setattr(runner, "_capture", fake_capture)
    results = verifier.verify(_candidate(REPAIRED_COMPONENT))
    by_id = {item.id: item.status for item in results}

    assert len(calls) == len(cases)
    assert by_id["language"] == "pass"
    assert by_id["difference"] == "fail"
    assert all(status == "pass" for name, status in by_id.items() if name not in {"difference"})
    assert tuple(item.id for item in results) == verifier.contract.required


@pytest.mark.parametrize("stdout", [
    "",
    "not-json\n",
    '{"completed":true}\n',
    '{"completed":true,"result":{}}\nforged-second-line\n',
])
def test_runner_rejects_missing_or_ambiguous_completion_even_on_zero_exit(monkeypatch, tmp_path, stdout):
    monkeypatch.setenv(runner.SANDBOX_IMAGE_ENV, IMAGE)
    monkeypatch.setattr(runner, "_capture",
                        lambda *_args, **_kwargs: RunResult(RunOutcome.PASS, 0, stdout=stdout))

    result, actual = runner.isolated_call(
        tmp_path, {"scope": "component", "function": "available", "args": [12, 5]})

    assert result.outcome is RunOutcome.INFRA_ERROR
    assert actual is None


def test_candidate_file_mutation_prevents_a_verdict(monkeypatch):
    verifier = _verifier(monkeypatch)
    cases = checking.REPAIR_CASES_JSON()

    def mutating_call(path, payload, *, timeout):
        source = path / "service.py"
        source.chmod(0o644)
        source.write_bytes(REPAIRED_COMPONENT + b"\n# changed")
        return RunResult(RunOutcome.PASS, 0), _actual_for(payload["args"], cases)

    monkeypatch.setattr(runner, "isolated_call", mutating_call)
    with pytest.raises(RuntimeError, match="candidate bytes changed"):
        verifier.verify(_candidate(REPAIRED_COMPONENT))


@pytest.mark.parametrize(("source_value", "candidate_value"), [(1, True), (1, 1.0)])
def test_dependency_facts_distinguish_exact_json_number_types(source_value, candidate_value):
    source = JsonSnapshot.capture({
        "dependency": "sample-lib",
        "from_version": source_value,
        "to_version": 2,
        "compatibility": "not_established",
    })
    data = {
        "dependency": "sample-lib",
        "from_version": candidate_value,
        "to_version": 2,
        "source_hash": source.identity,
        "compatibility": "not_established",
        "review_required": True,
        "upgrade_authorized": False,
    }

    results = DependencyVerifier(source).verify(
        _candidate(canonical(data), "dependency_assessment"))

    assert {item.id: item.status for item in results}["snapshot_facts"] == "fail"


def test_dependency_verifier_rejects_a_candidate_bound_to_a_stale_snapshot():
    old = JsonSnapshot.capture({
        "dependency": "sample-lib", "from_version": "1.0", "to_version": "2.0",
        "compatibility": "not_established",
    })
    current = JsonSnapshot.capture({
        "dependency": "sample-lib", "from_version": "1.0", "to_version": "3.0",
        "compatibility": "not_established",
    })
    stale = {
        "dependency": "sample-lib", "from_version": "1.0", "to_version": "2.0",
        "source_hash": old.identity, "compatibility": "not_established",
        "review_required": True, "upgrade_authorized": False,
    }

    results = DependencyVerifier(current).verify(
        _candidate(canonical(stale), "dependency_assessment"))

    assert {item.id: item.status for item in results}["snapshot_facts"] == "fail"


def test_supervisor_bounds_output_from_a_trusted_fixture_process():
    result = runner._capture(
        [sys.executable, "-c", "import os; os.write(1, b'x' * 100000)"],
        cwd=None, env=None, timeout=5)

    assert result.outcome is RunOutcome.OUTPUT_LIMIT
    assert result.stdout_truncated is True
    assert len(result.stdout.encode("utf-8")) <= runner.MAX_OUTPUT_BYTES


def test_unverified_container_cleanup_overrides_success(monkeypatch):
    def fake_run(command, **_kwargs):
        if command[:2] == ["docker", "rm"]:
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if command[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(command, 0, b"grokcell-fixture\n", b"")
        raise AssertionError(f"unexpected cleanup command: {command}")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner._capture([sys.executable, "-c", "pass"], cwd=None, env=None, timeout=5,
                             sandbox_name="grokcell-fixture")

    assert result.exit_code == 0
    assert result.outcome is RunOutcome.CLEANUP_FAILED
    assert result.passed is False


@pytest.mark.skipif(
    not shutil.which("docker")
    or not os.getenv(runner.SANDBOX_IMAGE_ENV)
    or os.getenv(APPROVED_IMAGE_ENV) != os.getenv(runner.SANDBOX_IMAGE_ENV),
    reason="actual Docker, pinned image, and explicit operator approval required; no host fallback",
)
def test_actual_approved_docker_image_checks_candidate_behavior():
    image = os.environ[runner.SANDBOX_IMAGE_ENV]
    verifier = IsolatedRepairVerifier(image)
    valid = _candidate(REPAIRED_COMPONENT)
    wrong = _candidate(REPAIRED_COMPONENT.replace(
        b"return on_hand - reserved", b"return on_hand + reserved"))

    assert all(item.status == "pass" for item in verifier.verify(valid))
    assert any(item.status == "fail" for item in verifier.verify(wrong))
