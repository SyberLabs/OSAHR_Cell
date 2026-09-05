from __future__ import annotations

import json
from pathlib import Path

from grokcell.fidelity import FidelityStore
from grokcell.mcp import McpServer
from grokcell.surface import GrokCellSurface
from grokcell.tools import TOOL_SCHEMAS, ToolRegistry


def _surface(tmp_path: Path) -> GrokCellSurface:
    return GrokCellSurface.open(
        fidelity=FidelityStore(tmp_path / "fidelity"),
        state=tmp_path / "state",
    )


def _mcp(tmp_path: Path) -> McpServer:
    return McpServer(ToolRegistry(_surface(tmp_path), bound_owner=None))


def _request(method: str, *, msg_id: int = 1, params: dict | None = None) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def _tool_text(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


def test_session_bind_is_not_a_new_tool():
    assert "session.bind" not in TOOL_SCHEMAS
    assert "oda.bind" not in TOOL_SCHEMAS


def test_ghost_cannot_bus_post(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    posted = tools.call(
        "bus.post",
        {
            "source_owner": "ghost",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {"name": "core.api", "constraint": "critical_module"},
        },
    )
    assert posted["queued"] is False
    assert posted["reason"] == "unknown_owner"
    assert posted["message_id"] == ""
    inspect = tools.call("surface.inspect", {})
    assert inspect["queued"] == 0
    assert inspect["owners"] == ["MOUTH"]


def test_omitted_source_owner_is_not_mouth(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    posted = tools.call(
        "bus.post",
        {
            "kind": "oda.spawn",
            "priority": 1,
            "payload": {"bot_name": "ghost"},
        },
    )
    assert posted["queued"] is False
    assert posted["reason"] in {"unknown_owner", "session_mismatch"}
    inspect = tools.call("surface.inspect", {})
    assert "ghost" not in inspect["owners"]
    assert inspect["queued"] == 0


def test_spawned_owner_can_post_after_bind(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    spawn = tools.call("oda.spawn", {"bot_name": "edge-sensor"})
    assert spawn["decision"] == "accepted"
    rebound = tools.bind("edge-sensor")
    assert rebound["decision"] == "accepted"
    posted = tools.call(
        "bus.post",
        {
            "source_owner": "edge-sensor",
            "kind": "oda.spawn",
            "priority": 1,
            "payload": {"bot_name": "leaf"},
        },
    )
    assert posted["queued"] is True
    drained = tools.call("bus.drain", {})
    assert drained["results"][0]["status"] == "admit"
    inspect = tools.call("surface.inspect", {})
    assert "leaf" in inspect["owners"]


def test_bound_mouth_cannot_post_as_another_owner(tmp_path: Path):
    tools = ToolRegistry(_surface(tmp_path))
    tools.call("oda.spawn", {"bot_name": "edge-sensor"})
    posted = tools.call(
        "bus.post",
        {
            "source_owner": "edge-sensor",
            "kind": "oda.spawn",
            "priority": 1,
            "payload": {"bot_name": "leaf"},
        },
    )
    assert posted["queued"] is False
    assert posted["reason"] == "session_mismatch"


def test_mcp_unbound_session_cannot_post(tmp_path: Path):
    server = _mcp(tmp_path)
    posted = server.handle(
        _request(
            "tools/call",
            params={
                "name": "bus.post",
                "arguments": {
                    "source_owner": "MOUTH",
                    "kind": "oda.spawn",
                    "priority": 1,
                    "payload": {"bot_name": "edge-sensor"},
                },
            },
        )
    )
    assert posted is not None
    body = _tool_text(posted)
    assert body["queued"] is False
    assert body["reason"] == "unbound_session"


def test_mcp_initialize_binds_a_registered_owner(tmp_path: Path):
    server = _mcp(tmp_path)
    init = server.handle(
        _request(
            "initialize",
            params={
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
                "owner": "MOUTH",
            },
        )
    )
    assert init is not None
    assert init["result"]["session"]["owner"] == "MOUTH"
    posted = server.handle(
        _request(
            "tools/call",
            msg_id=2,
            params={
                "name": "bus.post",
                "arguments": {
                    "source_owner": "MOUTH",
                    "kind": "oda.spawn",
                    "priority": 1,
                    "payload": {"bot_name": "edge-sensor"},
                },
            },
        )
    )
    assert posted is not None
    body = _tool_text(posted)
    assert body["queued"] is True


def test_mcp_cannot_rebind_to_another_owner(tmp_path: Path):
    server = _mcp(tmp_path)
    init = server.handle(
        _request(
            "initialize",
            params={
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
                "owner": "MOUTH",
            },
        )
    )
    assert init is not None
    assert init["result"]["session"]["owner"] == "MOUTH"
    spawn = server.handle(
        _request(
            "tools/call",
            msg_id=2,
            params={"name": "oda.spawn", "arguments": {"bot_name": "edge-sensor"}},
        )
    )
    assert spawn is not None
    assert _tool_text(spawn)["decision"] == "accepted"
    rebound = server.handle(
        _request(
            "initialize",
            msg_id=3,
            params={
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
                "owner": "edge-sensor",
            },
        )
    )
    assert rebound is not None
    assert rebound["error"]["code"] == -32602
    assert "already bound" in rebound["error"]["message"]
    posted = server.handle(
        _request(
            "tools/call",
            msg_id=4,
            params={
                "name": "bus.post",
                "arguments": {
                    "source_owner": "MOUTH",
                    "kind": "oda.spawn",
                    "priority": 1,
                    "payload": {"bot_name": "leaf"},
                },
            },
        )
    )
    assert posted is not None
    body = _tool_text(posted)
    assert body["queued"] is True


def test_mcp_cannot_connect_as_an_unregistered_owner(tmp_path: Path):
    server = _mcp(tmp_path)
    init = server.handle(
        _request(
            "initialize",
            params={
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
                "owner": "ghost",
            },
        )
    )
    assert init is not None
    assert "error" in init
    assert init["error"]["code"] == -32602
    assert "ghost" in init["error"]["message"]
