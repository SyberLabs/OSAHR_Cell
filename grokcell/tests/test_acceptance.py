from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from grokcell.acceptance import evaluate_acceptance, load_acceptance
from grokcell.artifact import Artifact, stage_artifact
from grokcell.fidelity import FidelityStore
from grokcell.mutant import kill_mutant
from grokcell.runner import RunOutcome, RunResult, pytest_suite
from grokcell.surface import GrokCellSurface
from grokcell.tools import ToolRegistry
from support import PING_ACCEPTANCE, register_acceptance

MODULE = "def ping():\n    return 'pong'\n"
CANDIDATE_TESTS = "from service import ping\n\ndef test_candidate():\n    assert ping() == 'pong'\n"


@pytest.fixture
def tools(tmp_path, monkeypatch):
    # Only these known fixture strings may execute on the development host.
    monkeypatch.setenv("GROKCELL_ALLOW_UNSANDBOXED_RUNNER", "1")
    return ToolRegistry(GrokCellSurface.open(
        fidelity=FidelityStore(tmp_path / "fidelity"), state=tmp_path / "state",
    ))


def propose(tools, *, name="edge.ping", module=MODULE, tests=CANDIDATE_TESTS, **extra):
    return tools.call("bus.post", {
        "source_owner": "MOUTH", "kind": "forge.propose", "priority": 999,
        "payload": {
            "name": name, "module": module, "tests": tests,
            "constraint": "critical_module", "depends_on": [], **extra,
        },
    })


def drain(tools):
    return tools.call("bus.drain", {})["results"][0]


@pytest.mark.parametrize("constraint", ["critical_module", "unverified"])
def test_mutually_wrong_module_and_candidate_tests_cannot_license_admission(
    tools, tmp_path, constraint,
):
    register_acceptance(tmp_path, "edge.ping")
    wrong_module = MODULE.replace("pong", "wrong")
    wrong_tests = CANDIDATE_TESTS.replace("pong", "wrong")
    old_gate = stage_artifact(Artifact(
        name="edge.ping", source="payload",
        files={"service.py": wrong_module, "test_service.py": wrong_tests},
    ), tmp_path / "old-gate")
    assert pytest_suite(old_gate, untrusted=True).passed
    assert kill_mutant(old_gate, untrusted=True) == (True, "mutant_killed")

    propose(tools, module=wrong_module, tests=wrong_tests, constraint=constraint,
            verified=True, acceptance_suite_hash="0" * 64,
            acceptance_tests=wrong_tests, acceptance_path=str(old_gate))
    result = drain(tools)
    assert (result["status"], result["reason"]) == ("reject", "acceptance_failed")
    assert tools.call("surface.inspect", {})["components"] == []
    assert not (tmp_path / "state" / "artifacts" / "edge.ping").exists()


@pytest.mark.parametrize("configured", [True, False])
def test_missing_suite_fails_before_executing_candidate(tools, monkeypatch, configured):
    if not configured:
        monkeypatch.delenv("GROKCELL_ACCEPTANCE_DIR")
    def must_not_run(*args, **kwargs):
        raise AssertionError("candidate executed without operator contract")
    monkeypatch.setattr("grokcell.bus.run_path", must_not_run)
    propose(tools, acceptance_tests=CANDIDATE_TESTS, acceptance_suite_hash="0" * 64)
    result = drain(tools)
    assert (result["status"], result["reason"]) == (
        "outcome_unknown", "acceptance_suite_missing",
    )


@pytest.mark.parametrize("damage,reason", [
    ("changed", "acceptance_suite_changed"),
    ("invalid_pin", "acceptance_suite_invalid"),
    ("invalid_utf8", "acceptance_suite_invalid"),
    ("empty", "acceptance_suite_invalid"),
    ("missing_pin", "acceptance_suite_missing"),
])
def test_bad_operator_suite_cannot_admit(tools, tmp_path, damage, reason):
    directory = register_acceptance(tmp_path, "edge.ping")
    if damage == "changed":
        (directory / "test_acceptance.py").write_text(PING_ACCEPTANCE + "# changed\n")
    elif damage == "invalid_pin":
        (directory / "test_acceptance.sha256").write_text("not a digest")
    elif damage == "invalid_utf8":
        (directory / "test_acceptance.py").write_bytes(b"\xff")
    elif damage == "empty":
        register_acceptance(tmp_path, "edge.ping", "")
    else:
        (directory / "test_acceptance.sha256").unlink()
    propose(tools)
    assert drain(tools)["reason"] == reason
    assert tools.call("surface.inspect", {})["artifacts"] == []


def test_symlink_contract_is_refused(tools, tmp_path):
    real = register_acceptance(tmp_path, "other.component")
    (tmp_path / "acceptance" / "edge.ping").symlink_to(real, target_is_directory=True)
    propose(tools)
    assert drain(tools)["reason"] == "acceptance_suite_invalid"


def test_invalid_configured_root_does_not_poison_queue(tools, tmp_path, monkeypatch):
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    monkeypatch.setenv("GROKCELL_ACCEPTANCE_DIR", str(loop))
    propose(tools)
    assert drain(tools)["reason"] == "acceptance_suite_invalid"
    assert tools.call("surface.inspect", {})["queued"] == 0


def test_operator_suite_is_snapshotted_before_candidate_execution(tools, tmp_path, monkeypatch):
    register_acceptance(tmp_path, "edge.ping")
    from grokcell import bus
    original = bus.run_path
    def change_contract_during_candidate_run(*args, **kwargs):
        register_acceptance(tmp_path, "edge.ping", PING_ACCEPTANCE.replace("pong", "wrong"))
        return original(*args, **kwargs)
    monkeypatch.setattr(bus, "run_path", change_contract_during_candidate_run)
    propose(tools, module=MODULE.replace("pong", "wrong"),
            tests=CANDIDATE_TESTS.replace("pong", "wrong"))
    assert drain(tools)["reason"] == "acceptance_failed"


def test_exact_artifact_and_acceptance_digest_survive_restart_and_file_acts(tools, tmp_path):
    tests = PING_ACCEPTANCE.replace("\n", "\r\n")
    register_acceptance(tmp_path, "edge.ping", tests)
    module = MODULE.replace("\n", "\r\n")
    propose(tools, module=module, verified=False)
    assert drain(tools)["status"] == "admit"
    root = tmp_path / "state" / "artifacts" / "edge.ping"
    assert (root / "service.py").read_bytes() == module.encode()
    assert not (root / "test_acceptance.py").exists()
    expected = hashlib.sha256(tests.encode()).hexdigest()
    before = json.loads((root / "license.json").read_text())
    assert before["acceptance_suite_hash"] == expected
    artifact = Artifact(name="edge.ping", source="payload", files={
        "service.py": module, "test_service.py": CANDIDATE_TESTS,
    })
    assert before["hash"] == artifact.digest()
    reopened = ToolRegistry(GrokCellSurface.open(
        fidelity=FidelityStore(tmp_path / "fidelity"), state=tmp_path / "state",
    ))
    assert reopened.call("surface.inspect", {})["artifacts"][0]["acceptance_suite_hash"] == expected
    for act in ("sign", "send", "publish", "delete"):
        assert reopened.call("park.request", {"act": act, "name": "edge.ping"})["decision"] == "accepted"
        record = json.loads((root / "license.json").read_text())
        assert record["hash"] == before["hash"]
        assert record["acceptance_suite_hash"] == expected


def test_weak_acceptance_suite_cannot_borrow_candidate_mutant_result(tools, tmp_path):
    register_acceptance(tmp_path, "edge.ping", "def test_weak():\n    assert True\n")
    propose(tools)
    assert drain(tools)["reason"] == "acceptance_mutant_survived"


@pytest.mark.parametrize("tests", ["def broken(:\n", "VALUE = 1\n"])
def test_invalid_or_uncollected_acceptance_is_infrastructure_failure(tools, tmp_path, tests):
    register_acceptance(tmp_path, "edge.ping", tests)
    propose(tools)
    assert drain(tools)["reason"] == "acceptance_infrastructure"


def test_acceptance_cannot_modify_tested_bytes(tools, tmp_path):
    register_acceptance(tmp_path, "edge.ping", PING_ACCEPTANCE + (
        "\ndef test_rewrite():\n"
        "    from pathlib import Path\n"
        "    Path('service.py').write_text('CHANGED = True\\n')\n"
    ))
    propose(tools)
    assert drain(tools)["reason"] == "acceptance_modified_artifact"


def test_candidate_tests_are_not_executed_in_acceptance_run(tools, tmp_path):
    register_acceptance(tmp_path, "edge.ping")
    tests = CANDIDATE_TESTS + (
        "\ndef test_candidate_context():\n"
        "    from pathlib import Path\n"
        "    assert not Path('test_acceptance.py').exists()\n"
    )
    propose(tools, tests=tests)
    assert drain(tools)["status"] == "admit"


def test_held_proposal_uses_current_contract_after_restart(tools, tmp_path):
    register_acceptance(tmp_path, "edge.ping")
    posted = propose(tools, depends_on=["core.api"])
    assert drain(tools)["status"] == "hold_unresolved"
    # Finish dependency through the existing frozen-suite path.
    from grokcell.runner import run_component
    run_component("core.api", store=FidelityStore(tmp_path / "fidelity"))
    tools.call("bus.post", {
        "source_owner": "MOUTH", "kind": "forge.propose", "priority": 1,
        "payload": {"name": "core.api", "constraint": "critical_module"},
    })
    assert drain(tools)["status"] == "admit"
    register_acceptance(tmp_path, "edge.ping", PING_ACCEPTANCE.replace("pong", "new-contract"))
    reopened = ToolRegistry(GrokCellSurface.open(
        fidelity=FidelityStore(tmp_path / "fidelity"), state=tmp_path / "state",
    ))
    request = {"status": "hold_unresolved", "message_id": posted["message_id"]}
    refused = reopened.call("park.request", request)
    assert (refused["decision"], refused["reason"]) == ("refused", "acceptance_failed")
    assert reopened.call("surface.inspect", {})["hold_queue"] == 1
    register_acceptance(tmp_path, "edge.ping")
    assert reopened.call("park.request", request)["decision"] == "accepted"


def test_generated_payload_cannot_use_reserved_component_name(tools):
    propose(tools, name="core.api")
    assert drain(tools)["reason"] == "reserved_component_name"


@pytest.mark.parametrize("outcome,reason", [
    (RunOutcome.TIMEOUT, "acceptance_timeout"),
    (RunOutcome.INFRA_ERROR, "acceptance_infrastructure"),
    (RunOutcome.SANDBOX_REQUIRED, "runner_sandbox_required"),
])
def test_acceptance_runner_errors_fail_closed(tmp_path, monkeypatch, outcome, reason):
    register_acceptance(tmp_path, "edge.ping")
    suite = load_acceptance("edge.ping")
    artifact = Artifact(name="edge.ping", files={"service.py": MODULE}, source="payload")
    monkeypatch.setattr("grokcell.acceptance.pytest_suite", lambda *a, **kw: RunResult(outcome, -1))
    assert evaluate_acceptance(artifact, suite) == (False, reason)
