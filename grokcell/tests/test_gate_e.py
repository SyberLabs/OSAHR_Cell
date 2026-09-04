from __future__ import annotations

from pathlib import Path

import pytest

from grokcell.fidelity import FidelityStore
from grokcell.runner import run_component
from grokcell.surface import GrokCellSurface
from grokcell.tools import TOOL_SCHEMAS, ToolRegistry


MODULE_PING = "def ping() -> str:\n    return \"pong\"\n"
TESTS_PING = "from service import ping\n\n\ndef test_ping_returns_pong():\n    assert ping() == \"pong\"\n"
TESTS_WEAK = "def test_always_passes():\n    assert True\n"


@pytest.fixture(autouse=True)
def allow_trusted_generated_code(monkeypatch):
    monkeypatch.setenv("GROKCELL_ALLOW_UNSANDBOXED_RUNNER", "1")


def _scored(tmp_path: Path, *names: str) -> tuple[FidelityStore, Path]:
    store = FidelityStore(tmp_path / "fidelity")
    for name in names:
        record = run_component(name, store=store)
        if not record.passed:
            raise AssertionError(f"runner failed for {name}: exit {record.exit_code}")
    return store, tmp_path / "state"


def _surface(tmp_path: Path, *names: str) -> GrokCellSurface:
    store, state = _scored(tmp_path, *names)
    return GrokCellSurface.open(fidelity=store, state=state)


def _propose(
    tools: ToolRegistry,
    name: str,
    *,
    depends_on: list[str] | None = None,
    module: str | None = None,
    tests: str | None = None,
    constraint: str = "critical_module",
    verified: bool = True,
) -> dict:
    payload: dict = {
        "name": name,
        "constraint": constraint,
        "depends_on": depends_on or [],
        "verified": verified,
    }
    if module is not None:
        payload["module"] = module
    if tests is not None:
        payload["tests"] = tests
    return tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": payload,
        },
    )


def test_artifact_acts_are_not_new_tools():
    names = set(TOOL_SCHEMAS)
    assert "artifact.write" not in names
    assert "park.send" not in names
    assert "park.publish" not in names
    assert "park.delete" not in names
    assert "park.sign" not in names
    assert "mutant.kill" not in names


def test_admit_writes_module_and_tests(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path, "core.api"))
    _propose(tools, "core.api")
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    inspect = tools.call("surface.inspect", {})
    names = [item["name"] for item in inspect["artifacts"]]
    assert "core.api" in names
    root = tmp_path / "state" / "artifacts" / "core.api"
    assert (root / "service.py").is_file()
    assert (root / "test_service.py").is_file()
    assert "pong" in (root / "service.py").read_text(encoding="utf-8")


def test_weak_suite_is_rejected_and_writes_nothing(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    _propose(tools, "edge.weak", module=MODULE_PING, tests=TESTS_WEAK)
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "reject"
    assert drained["results"][0]["reason"] == "mutant_survived"
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == []
    assert inspect["artifacts"] == []
    assert not (tmp_path / "state" / "artifacts" / "edge.weak").exists()


def test_generated_module_admits_when_tests_kill_mutants(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    _propose(tools, "edge.ping", module=MODULE_PING, tests=TESTS_PING, verified=False)
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == ["edge.ping"]
    root = tmp_path / "state" / "artifacts" / "edge.ping"
    assert (root / "service.py").read_text(encoding="utf-8") == MODULE_PING
    assert (root / "test_service.py").read_text(encoding="utf-8") == TESTS_PING


def test_generated_crlf_bytes_are_tested_and_preserved(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    module = MODULE_PING.replace("\n", "\r\n")
    tests = TESTS_PING.replace("\n", "\r\n")
    _propose(tools, "edge.crlf", module=module, tests=tests, verified=False)
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    root = tmp_path / "state" / "artifacts" / "edge.crlf"
    assert (root / "service.py").read_bytes() == module.encode("utf-8")
    assert (root / "test_service.py").read_bytes() == tests.encode("utf-8")


def test_missing_artifact_is_outcome_unknown(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    _propose(tools, "ghost.mod")
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "outcome_unknown"
    assert drained["results"][0]["reason"] == "missing_artifact"
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == []
    assert inspect["artifacts"] == []


def test_artifacts_survive_reopen(tmp_path: Path):
    store, state = _scored(tmp_path, "core.api")
    first = GrokCellSurface.open(fidelity=store, state=state)
    tools = ToolRegistry(first)
    _propose(tools, "core.api")
    tools.call("bus.drain", {})
    before = tools.call("surface.inspect", {})
    assert "core.api" in [item["name"] for item in before["artifacts"]]

    second = GrokCellSurface.open(fidelity=store, state=state)
    after = ToolRegistry(second).call("surface.inspect", {})
    assert id(second.runtime) != id(first.runtime)
    assert after["components"] == ["core.api"]
    root = state / "artifacts" / "core.api"
    assert (root / "service.py").is_file()
    assert (root / "test_service.py").is_file()
    assert after["artifacts"][0]["name"] == "core.api"


def test_park_commit_writes_held_artifact(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path, "core.api", "app.ui"))
    _propose(tools, "app.ui", depends_on=["core.api"])
    tools.call("bus.drain", {})
    message_id = tools.call("surface.inspect", {})["held"][0]["message_id"]
    assert not (tmp_path / "state" / "artifacts" / "app.ui").exists()
    _propose(tools, "core.api")
    tools.call("bus.drain", {})
    accepted = tools.call(
        "park.request",
        {"status": "hold_unresolved", "message_id": message_id},
    )
    assert accepted["decision"] == "accepted"
    assert accepted["bypasses_dpo"] is False
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == ["core.api", "app.ui"]
    assert (tmp_path / "state" / "artifacts" / "app.ui" / "service.py").is_file()


def test_park_file_acts_do_not_rewrite_g(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path, "core.api"))
    _propose(tools, "core.api")
    tools.call("bus.drain", {})
    before = tools.call("surface.inspect", {})
    signed = tools.call("park.request", {"act": "sign", "name": "core.api"})
    assert signed["decision"] == "accepted"
    assert signed["bypasses_dpo"] is False
    sent = tools.call("park.request", {"act": "send", "name": "core.api"})
    assert sent["decision"] == "accepted"
    published = tools.call("park.request", {"act": "publish", "name": "core.api"})
    assert published["decision"] == "accepted"
    after = tools.call("surface.inspect", {})
    assert after["state_hash"] == before["state_hash"]
    assert after["components"] == ["core.api"]
    licenses = {item["name"]: item["license"] for item in after["artifacts"]}
    assert licenses["core.api"] == "published"
    root = tmp_path / "state" / "artifacts" / "core.api"
    assert (root / "signature.txt").is_file()
    deleted = tools.call("park.request", {"act": "delete", "name": "core.api"})
    assert deleted["decision"] == "accepted"
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == ["core.api"]
    assert inspect["state_hash"] == before["state_hash"]
    assert not (root / "service.py").exists()
    leftover = {item["name"]: item["license"] for item in inspect["artifacts"]}
    assert leftover["core.api"] == "deleted"


def test_park_refuses_file_act_without_artifact(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    refused = tools.call("park.request", {"act": "sign", "name": "core.api"})
    assert refused["decision"] == "refused"
    assert refused["bypasses_dpo"] is False
    assert refused["reason"] == "component_not_admitted"
