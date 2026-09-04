from __future__ import annotations

from grokcell.surface import GrokCellSurface
from grokcell.tools import TOOL_SCHEMAS, ToolRegistry


def _propose(tools: ToolRegistry, name: str, *, verified: bool, depends_on: list[str] | None = None) -> dict:
    return tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": name,
                "constraint": "critical_module",
                "verified": verified,
                "depends_on": depends_on or [],
            },
        },
    )


def test_runner_is_not_a_bot_tool():
    names = set(TOOL_SCHEMAS)
    assert "runner.score" not in names
    assert "fidelity.write" not in names
    assert "python_tests" not in names


def test_client_verified_true_is_ignored_when_runner_absent(tmp_path):
    from grokcell.fidelity import FidelityStore

    surface = GrokCellSurface.open(fidelity=FidelityStore(tmp_path))
    tools = ToolRegistry(surface)
    _propose(tools, "core.api", verified=True)
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "reject"
    assert drained["results"][0]["reason"] == "runner_absent"
    assert tools.call("surface.inspect", {})["components"] == []


def test_runner_pass_admits_without_client_verified():
    from grokcell.fidelity import FidelityStore
    from grokcell.runner import run_component
    from grokcell.surface import GrokCellSurface
    from pathlib import Path
    import tempfile

    root = Path(tempfile.mkdtemp())
    store = FidelityStore(root)
    record = run_component("core.api", store=store)
    assert record.passed is True
    surface = GrokCellSurface.open(fidelity=store)
    tools = ToolRegistry(surface)
    _propose(tools, "core.api", verified=False)
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    assert drained["results"][0]["reason"] == "vault_legal"
    assert tools.call("surface.inspect", {})["components"] == ["core.api"]


def test_runner_failure_is_fail_closed():
    from grokcell.fidelity import FidelityStore
    from grokcell.runner import run_component
    from pathlib import Path
    import tempfile

    store = FidelityStore(Path(tempfile.mkdtemp()))
    record = run_component("failing.example", store=store)
    assert record.passed is False
    surface = GrokCellSurface.open(fidelity=store)
    tools = ToolRegistry(surface)
    _propose(tools, "failing.example", verified=True)
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "reject"
    assert drained["results"][0]["reason"] == "runner_failed"
    assert tools.call("surface.inspect", {})["components"] == []


def test_stale_fidelity_hash_is_rejected():
    from grokcell.fidelity import FidelityRecord, FidelityStore
    from grokcell.runner import suite_hash, suite_path
    from pathlib import Path
    import tempfile

    store = FidelityStore(Path(tempfile.mkdtemp()))
    store.put(
        FidelityRecord(
            name="core.api",
            passed=True,
            suite_hash="not-the-current-suite",
            exit_code=0,
        )
    )
    assert suite_hash(suite_path("core.api")) != "not-the-current-suite"
    surface = GrokCellSurface.open(fidelity=store)
    tools = ToolRegistry(surface)
    _propose(tools, "core.api", verified=True)
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "reject"
    assert drained["results"][0]["reason"] == "stale_fidelity"
