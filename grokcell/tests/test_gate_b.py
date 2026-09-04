from __future__ import annotations

from pathlib import Path

from grokcell.fidelity import FidelityStore
from grokcell.runner import run_component
from grokcell.surface import GrokCellSurface
from grokcell.tools import TOOL_SCHEMAS, ToolRegistry


def _scored(tmp_path: Path, *names: str) -> tuple[FidelityStore, Path]:
    store = FidelityStore(tmp_path / "fidelity")
    for name in names:
        record = run_component(name, store=store)
        if not record.passed:
            raise AssertionError(f"runner failed for {name}: exit {record.exit_code}")
    return store, tmp_path / "state"


def _propose(tools: ToolRegistry, name: str, *, depends_on: list[str] | None = None) -> dict:
    return tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": name,
                "constraint": "critical_module",
                "depends_on": depends_on or [],
            },
        },
    )


def test_snapshot_is_not_a_bot_tool():
    names = set(TOOL_SCHEMAS)
    assert "snapshot.save" not in names
    assert "snapshot.load" not in names
    assert "state.write" not in names


def test_open_without_snapshot_is_a_fresh_empty_cell(tmp_path: Path):
    store, state = _scored(tmp_path, "core.api")
    surface = GrokCellSurface.open(fidelity=store, state=state)
    inspect = ToolRegistry(surface).call("surface.inspect", {})
    assert inspect["components"] == []
    assert inspect["owners"] == ["MOUTH"]
    assert inspect["queued"] == 0
    assert inspect["hold_queue"] == 0
    assert inspect["event_index"] == 0


def test_admit_survives_a_new_open_on_the_same_state_dir(tmp_path: Path):
    store, state = _scored(tmp_path, "core.api")
    first = GrokCellSurface.open(fidelity=store, state=state)
    tools = ToolRegistry(first)
    _propose(tools, "core.api")
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    before = tools.call("surface.inspect", {})
    assert before["components"] == ["core.api"]

    second = GrokCellSurface.open(fidelity=store, state=state)
    after = ToolRegistry(second).call("surface.inspect", {})
    assert id(second.runtime) != id(first.runtime)
    assert after["components"] == ["core.api"]
    assert after["state_hash"] == before["state_hash"]
    assert after["event_index"] == before["event_index"]
    assert after["owners"] == before["owners"]


def test_held_queue_survives_reopen(tmp_path: Path):
    store, state = _scored(tmp_path, "app.ui")
    first = GrokCellSurface.open(fidelity=store, state=state)
    tools = ToolRegistry(first)
    _propose(tools, "app.ui", depends_on=["core.api"])
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "hold_unresolved"
    held = tools.call("surface.inspect", {})["held"]
    assert len(held) == 1
    message_id = held[0]["message_id"]

    second = GrokCellSurface.open(fidelity=store, state=state)
    resumed = ToolRegistry(second).call("surface.inspect", {})
    assert resumed["hold_queue"] == 1
    assert resumed["held"][0]["message_id"] == message_id
    assert resumed["held"][0]["payload"]["name"] == "app.ui"
    assert resumed["components"] == []


def test_undrained_queue_survives_reopen(tmp_path: Path):
    store, state = _scored(tmp_path, "core.api")
    first = GrokCellSurface.open(fidelity=store, state=state)
    tools = ToolRegistry(first)
    posted = _propose(tools, "core.api")
    assert posted["queued"] is True
    assert tools.call("surface.inspect", {})["queued"] == 1

    second = GrokCellSurface.open(fidelity=store, state=state)
    resumed = ToolRegistry(second)
    inspect = resumed.call("surface.inspect", {})
    assert inspect["queued"] == 1
    assert inspect["components"] == []
    drained = resumed.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    assert resumed.call("surface.inspect", {})["components"] == ["core.api"]


def test_spawned_owner_and_skills_survive_reopen(tmp_path: Path):
    store, state = _scored(tmp_path)
    first = GrokCellSurface.open(fidelity=store, state=state)
    tools = ToolRegistry(first)
    spawn = tools.call("oda.spawn", {"bot_name": "edge-sensor", "job": "anlf"})
    assert spawn["decision"] == "accepted"
    attached = tools.call(
        "oda.attach_skill",
        {"owner": "edge-sensor", "skill": "grokcell-forge", "rail": "construct-component"},
    )
    assert attached["decision"] == "accepted"
    before = tools.call("surface.inspect", {})

    second = GrokCellSurface.open(fidelity=store, state=state)
    after = ToolRegistry(second).call("surface.inspect", {})
    assert "edge-sensor" in after["owners"]
    assert after["bots_spawned"] == 1
    assert "grokcell-forge" in after["skills"]["edge-sensor"]
    assert after["components"] == []
    assert after["event_index"] == before["event_index"]
    assert after["state_hash"] == before["state_hash"]


def test_park_after_reopen_still_commits_through_dpo(tmp_path: Path):
    store, state = _scored(tmp_path, "core.api", "app.ui")
    first = GrokCellSurface.open(fidelity=store, state=state)
    tools = ToolRegistry(first)
    _propose(tools, "app.ui", depends_on=["core.api"])
    tools.call("bus.drain", {})
    message_id = tools.call("surface.inspect", {})["held"][0]["message_id"]
    _propose(tools, "core.api")
    tools.call("bus.drain", {})
    assert tools.call("surface.inspect", {})["components"] == ["core.api"]

    second = GrokCellSurface.open(fidelity=store, state=state)
    resumed = ToolRegistry(second)
    accepted = resumed.call(
        "park.request",
        {"status": "hold_unresolved", "message_id": message_id},
    )
    assert accepted["decision"] == "accepted"
    assert accepted["bypasses_dpo"] is False
    inspect = resumed.call("surface.inspect", {})
    assert inspect["components"] == ["core.api", "app.ui"]
    assert inspect["hold_queue"] == 0


def test_incomplete_snapshot_fail_closes(tmp_path: Path):
    store, state = _scored(tmp_path)
    state.mkdir(parents=True)
    (state / "kernel.osahr.gz").write_bytes(b"not-a-checkpoint")
    try:
        GrokCellSurface.open(fidelity=store, state=state)
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("expected incomplete snapshot to fail closed")
