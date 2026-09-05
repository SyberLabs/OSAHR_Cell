"""MCP stdio host wrapping ToolRegistry.call. Same schemas. Not HTTP."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

_GROKCELL_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _GROKCELL_ROOT.parent
for _path in (str(_GROKCELL_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from .protocol import MCP_SCHEMA_VERSION
from .surface import GrokCellSurface
from .tools import ToolRegistry

PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")


def _encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _ok(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


class McpServer:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = str(message.get("method") or "")
        msg_id = message["id"] if "id" in message else None
        if msg_id is None:
            return None
        if not method:
            return _error(msg_id, -32600, "Invalid Request")
        if method == "initialize":
            params = message.get("params") or {}
            owner = str(params.get("owner") or "").strip()
            if owner:
                current = self.tools.bound_owner
                if current is not None and owner != current:
                    return _error(msg_id, -32602, "Session already bound")
                bound = self.tools.bind(owner)
                if bound["decision"] != "accepted":
                    return _error(msg_id, -32602, f"Unknown owner: {owner}")
            result = self._initialize(params)
            result["session"] = {"owner": self.tools.bound_owner}
            return _ok(msg_id, result)
        if method == "ping":
            return _ok(msg_id, {})
        if method == "tools/list":
            return _ok(msg_id, {"tools": self.tools.schemas})
        if method == "tools/call":
            return self._call(msg_id, message.get("params") or {})
        return _error(msg_id, -32601, f"Method not found: {method}")

    def handle_line(self, line: str) -> str | None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return _encode(_error(None, -32700, "Parse error"))
        if not isinstance(message, dict):
            return _encode(_error(None, -32600, "Invalid Request"))
        response = self.handle(message)
        if response is None:
            return None
        return _encode(response)

    def serve_stdio(self, stdin: TextIO, stdout: TextIO) -> None:
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            encoded = self.handle_line(line)
            if encoded is None:
                continue
            stdout.write(encoded + "\n")
            stdout.flush()

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = str(params.get("protocolVersion") or PROTOCOL_VERSION)
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "grokcell", "version": MCP_SCHEMA_VERSION},
        }

    def _call(self, msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        if not name:
            return _error(msg_id, -32602, "Missing tool name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(msg_id, -32602, "Tool arguments must be an object")
        try:
            result = self.tools.call(name, arguments)
        except KeyError:
            return _error(msg_id, -32602, f"Unknown tool: {name}")
        except Exception as exc:
            return _ok(
                msg_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        return _ok(
            msg_id,
            {"content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}]},
        )


def main() -> None:
    server = McpServer(ToolRegistry(GrokCellSurface.open(), bound_owner=None))
    server.serve_stdio(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
