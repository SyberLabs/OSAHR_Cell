from __future__ import annotations

from grokcell.surface import GrokCellSurface
from grokcell.tools import ToolRegistry


def test_spawn_is_always_refused_in_v0():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    posted = tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "oda.spawn",
            "priority": 100,
            "payload": {"bot_name": "specialist-router"},
        },
    )
    assert posted["queued"] is True
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "reject"
    assert drained["results"][0]["reason"] == "oda_spawn_lock"
    spawn = tools.call(
        "oda.spawn",
        {"bot_name": "specialist-router", "job": "message passing"},
    )
    assert spawn["decision"] == "refused"
    inspect = tools.call("surface.inspect", {})
    owners = inspect["owners"]
    assert owners == ["MOUTH"]
    assert inspect["bots_spawned"] == 0


def test_attach_skill_is_a_rail_on_the_existing_owner():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    attached = tools.call(
        "oda.attach_skill",
        {"owner": "MOUTH", "skill": "grokcell-forge", "rail": "construct-component"},
    )
    assert attached["decision"] == "accepted"
    assert attached["new_bot"] is False
    inspect = tools.call("surface.inspect", {})
    assert inspect["owners"] == ["MOUTH"]
    assert "grokcell-forge" in inspect["skills_on_mouth"]
