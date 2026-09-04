from __future__ import annotations

from grokcell.surface import GrokCellSurface
from grokcell.tools import ToolRegistry


def test_spawn_registers_an_owner_without_rewriting_g():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    before = tools.call("surface.inspect", {})
    posted = tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "oda.spawn",
            "priority": 100,
            "payload": {"bot_name": "specialist-router", "job": "message passing"},
        },
    )
    assert posted["queued"] is True
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    assert drained["results"][0]["reason"] != "oda_spawn_lock"
    spawn = tools.call(
        "oda.spawn",
        {"bot_name": "edge-sensor", "job": "anlf payloads"},
    )
    assert spawn["decision"] == "accepted"
    assert spawn["new_bot"] is True
    inspect = tools.call("surface.inspect", {})
    assert "MOUTH" in inspect["owners"]
    assert "specialist-router" in inspect["owners"]
    assert "edge-sensor" in inspect["owners"]
    assert inspect["bots_spawned"] == 2
    assert inspect["components"] == []
    assert inspect["event_index"] == before["event_index"]
    assert inspect["time"] == before["time"]
    assert "assemble-component" in inspect["rule_ids"]


def test_duplicate_spawn_is_rejected():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    first = tools.call("oda.spawn", {"bot_name": "edge-sensor"})
    assert first["decision"] == "accepted"
    second = tools.call("oda.spawn", {"bot_name": "edge-sensor"})
    assert second["decision"] == "refused"
    assert second["reason"] == "duplicate_owner"
    inspect = tools.call("surface.inspect", {})
    assert inspect["owners"].count("edge-sensor") == 1
    assert inspect["bots_spawned"] == 1


def test_attach_skill_on_a_spawned_owner():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    tools.call("oda.spawn", {"bot_name": "edge-sensor", "job": "anlf"})
    attached = tools.call(
        "oda.attach_skill",
        {"owner": "edge-sensor", "skill": "grokcell-forge", "rail": "construct-component"},
    )
    assert attached["decision"] == "accepted"
    assert attached["new_bot"] is False
    inspect = tools.call("surface.inspect", {})
    assert "grokcell-forge" in inspect["skills"]["edge-sensor"]
    mouth_only = tools.call(
        "oda.attach_skill",
        {"owner": "MOUTH", "skill": "grokcell-recon", "rail": "vault-query"},
    )
    assert mouth_only["decision"] == "accepted"
    inspect = tools.call("surface.inspect", {})
    assert "grokcell-recon" in inspect["skills"]["MOUTH"]


def test_attach_skill_unknown_owner_is_refused():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    attached = tools.call(
        "oda.attach_skill",
        {"owner": "ghost", "skill": "grokcell-forge", "rail": "x"},
    )
    assert attached["decision"] == "refused"
    assert attached["reason"] == "unknown_owner"
