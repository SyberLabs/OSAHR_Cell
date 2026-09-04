from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from grokcell.fidelity import FidelityStore
from grokcell.mcp import McpServer
from grokcell.surface import GrokCellSurface
from grokcell.tools import TOOL_SCHEMAS, ToolRegistry


def _server(tmp_path: Path) -> McpServer:
    surface = GrokCellSurface.open(
        fidelity=FidelityStore(tmp_path / "fidelity"),
        state=tmp_path / "state",
    )
    return McpServer(ToolRegistry(surface))


def _request(method: str, *, msg_id: int = 1, params: dict | None = None) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def test_mcp_lists_exactly_the_existing_tool_names(tmp_path: Path):
    listed = _server(tmp_path).handle(_request("tools/list", params={}))
    assert listed is not None
    names = [item["name"] for item in listed["result"]["tools"]]
    assert set(names) == set(TOOL_SCHEMAS)
    assert "runner.score" not in names
    assert "snapshot.save" not in names
    assert "http.post" not in names


def test_mcp_initialize_declares_tools_capability(tmp_path: Path):
    response = _server(tmp_path).handle(
        _request(
            "initialize",
            params={
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        )
    )
    assert response is not None
    result = response["result"]
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "grokcell"
    assert "protocolVersion" in result


def test_mcp_initialized_notification_has_no_response(tmp_path: Path):
    response = _server(tmp_path).handle(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert response is None


def test_mcp_tools_call_wraps_the_existing_registry(tmp_path: Path):
    server = _server(tmp_path)
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
    ack = json.loads(posted["result"]["content"][0]["text"])
    assert ack["queued"] is True
    drained = server.handle(
        _request("tools/call", msg_id=2, params={"name": "bus.drain", "arguments": {}})
    )
    assert drained is not None
    body = json.loads(drained["result"]["content"][0]["text"])
    assert body["results"][0]["status"] == "admit"
    inspect = server.handle(
        _request(
            "tools/call",
            msg_id=3,
            params={"name": "surface.inspect", "arguments": {}},
        )
    )
    assert inspect is not None
    snapshot = json.loads(inspect["result"]["content"][0]["text"])
    assert "edge-sensor" in snapshot["owners"]
    assert snapshot["components"] == []


def test_mcp_unknown_tool_is_a_protocol_error(tmp_path: Path):
    response = _server(tmp_path).handle(
        _request(
            "tools/call",
            params={"name": "runner.score", "arguments": {"name": "core.api"}},
        )
    )
    assert response is not None
    assert "error" in response
    assert response["error"]["code"] == -32602
    assert "runner.score" in response["error"]["message"]


def test_mcp_unknown_method_is_method_not_found(tmp_path: Path):
    response = _server(tmp_path).handle(_request("tools/invent"))
    assert response is not None
    assert response["error"]["code"] == -32601


def test_mcp_stdio_roundtrip_initialize_and_list(tmp_path: Path):
    grokcell_root = Path(__file__).resolve().parents[1]
    repo_root = grokcell_root.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(grokcell_root), str(repo_root)))
    env["GROKCELL_STATE_DIR"] = str(tmp_path / "state")
    env["GROKCELL_FIDELITY_DIR"] = str(tmp_path / "fidelity")
    proc = subprocess.Popen(
        [sys.executable, "-m", "grokcell.mcp"],
        cwd=str(grokcell_root),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    def rpc(message: dict) -> dict:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        assert line, proc.stderr.read() if proc.stderr else "no stdout"
        parsed = json.loads(line)
        assert "\n" not in line[:-1]
        return parsed

    try:
        init = rpc(
            _request(
                "initialize",
                params={
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            )
        )
        assert "tools" in init["result"]["capabilities"]
        proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        proc.stdin.flush()
        listed = rpc(_request("tools/list", msg_id=2, params={}))
        names = {item["name"] for item in listed["result"]["tools"]}
        assert names == set(TOOL_SCHEMAS)
    finally:
        proc.stdin.close()
        try:
            code = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            raise
        if code != 0:
            err = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"mcp exit {code}: {err}")
