from __future__ import annotations

from pathlib import Path

from grokcell.messages import Message
from grokcell.surface import GrokCellSurface
from grokcell.tools import ToolRegistry, TOOL_SCHEMAS

from support import scored_surface


def test_tool_ports_are_not_occurrence_types():
    assert "oda.spawn" in TOOL_SCHEMAS
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    inspect = tools.call("surface.inspect", {})
    rule_ids = set(inspect["rule_ids"])
    assert "bus.post" not in rule_ids
    assert "oda.spawn" not in rule_ids
    assert "assemble-component" in rule_ids


def test_constraints_outrank_priority(tmp_path: Path):
    from grokcell.fidelity import FidelityStore

    surface = GrokCellSurface.open(fidelity=FidelityStore(tmp_path))
    tools = ToolRegistry(surface)
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 99,
            "payload": {
                "name": "core.api",
                "constraint": "critical_module",
                "verified": True,
                "depends_on": [],
            },
        },
    )
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "oda.spawn",
            "priority": 1,
            "payload": {"bot_name": "edge-sensor"},
        },
    )
    drained = tools.call("bus.drain", {})
    spawn = next(item for item in drained["results"] if item["kind"] == "oda.spawn")
    propose = next(item for item in drained["results"] if item["kind"] == "forge.propose")
    assert spawn["status"] == "admit"
    assert propose["status"] == "reject"
    assert propose["reason"] == "runner_absent"
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == []
    assert "edge-sensor" in inspect["owners"]
    assert inspect["bots_spawned"] == 1


def test_missing_dependency_holds(tmp_path: Path):
    surface = scored_surface("app.ui", root=tmp_path)
    tools = ToolRegistry(surface)
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 10,
            "payload": {
                "name": "app.ui",
                "constraint": "critical_module",
                "depends_on": ["core.api"],
            },
        },
    )
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "hold_unresolved"
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == []
    assert inspect["hold_queue"] == 1


def test_unverified_critical_is_rejected(tmp_path: Path):
    from grokcell.fidelity import FidelityStore

    surface = GrokCellSurface.open(fidelity=FidelityStore(tmp_path))
    tools = ToolRegistry(surface)
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 10,
            "payload": {
                "name": "core.api",
                "constraint": "critical_module",
                "verified": False,
                "depends_on": [],
            },
        },
    )
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "reject"
    assert drained["results"][0]["reason"] == "runner_absent"
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == []


def test_unknown_constraint_is_outcome_unknown():
    surface = GrokCellSurface.open()
    posted = surface.post(
        Message(
            source_owner="MOUTH",
            kind="forge.propose",
            priority=1,
            payload={
                "name": "x",
                "constraint": "not-a-concept",
                "verified": True,
                "depends_on": [],
            },
        )
    )
    assert posted.queued
    results = surface.drain()
    assert results[0].status == "outcome_unknown"
