from __future__ import annotations

from grokcell.surface import GrokCellSurface
from grokcell.tools import ToolRegistry


def test_sequential_construction_commits_through_the_kernel():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    before = tools.call("surface.inspect", {})
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 5,
            "payload": {
                "name": "core.api",
                "constraint": "critical_module",
                "verified": True,
                "depends_on": [],
            },
        },
    )
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    after = tools.call("surface.inspect", {})
    assert after["components"] == ["core.api"]
    assert after["state_hash"] != before["state_hash"]
    assert after["event_index"] >= 1

    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 5,
            "payload": {
                "name": "app.ui",
                "constraint": "critical_module",
                "verified": True,
                "depends_on": ["core.api"],
            },
        },
    )
    second = tools.call("bus.drain", {})
    assert second["results"][0]["status"] == "admit"
    final = tools.call("surface.inspect", {})
    assert final["components"] == ["core.api", "app.ui"]


def test_park_refuses_unless_hold():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": "app.ui",
                "constraint": "critical_module",
                "verified": True,
                "depends_on": ["core.api"],
            },
        },
    )
    tools.call("bus.drain", {})
    inspect = tools.call("surface.inspect", {})
    message_id = inspect["held"][0]["message_id"]
    for status in ("admit", "reject", "outcome_unknown"):
        payload = tools.call(
            "park.request",
            {"status": status, "message_id": message_id},
        )
        assert payload["decision"] == "refused"
        assert payload["bypasses_dpo"] is False
    held = tools.call(
        "park.request",
        {"status": "hold_unresolved", "message_id": message_id},
    )
    assert held["decision"] == "refused"
    assert "dependency" in held["reason"]


def test_park_at_hold_commits_when_deps_exist():
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": "app.ui",
                "constraint": "critical_module",
                "verified": True,
                "depends_on": ["core.api"],
            },
        },
    )
    tools.call("bus.drain", {})
    message_id = tools.call("surface.inspect", {})["held"][0]["message_id"]
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": "core.api",
                "constraint": "critical_module",
                "verified": True,
                "depends_on": [],
            },
        },
    )
    tools.call("bus.drain", {})
    assert tools.call("surface.inspect", {})["components"] == ["core.api"]
    accepted = tools.call(
        "park.request",
        {"status": "hold_unresolved", "message_id": message_id},
    )
    assert accepted["decision"] == "accepted"
    inspect = tools.call("surface.inspect", {})
    assert inspect["components"] == ["core.api", "app.ui"]
    assert inspect["hold_queue"] == 0


def test_no_llm_in_surface_modules():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "grokcell"
    forbidden = ("openai", "anthropic", "groq", "litellm", "transformers")
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in text
            assert f"import {name}" not in text
