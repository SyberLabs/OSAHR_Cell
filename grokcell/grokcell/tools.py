"""Agent-facing tool ports. Recon and park. Not radio links."""
from __future__ import annotations

from typing import Any, Callable

from .messages import Message
from .protocol import MCP_SCHEMA_VERSION, MOUTH_OWNER
from .surface import GrokCellSurface

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "vault.query": {
        "name": "vault.query",
        "description": "Read a constraint concept. Dual projection; no SPARQL.",
        "inputSchema": {
            "type": "object",
            "properties": {"concept_id": {"type": "string"}},
            "required": ["concept_id"],
        },
    },
    "bus.post": {
        "name": "bus.post",
        "description": "Queue a typed control-plane message. Does not rewrite G.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_owner": {"type": "string"},
                "kind": {"type": "string"},
                "priority": {"type": "integer"},
                "payload": {"type": "object"},
            },
            "required": ["source_owner", "kind", "priority", "payload"],
        },
    },
    "bus.drain": {
        "name": "bus.drain",
        "description": "Classify queued messages. admit commits via the kernel.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "surface.inspect": {
        "name": "surface.inspect",
        "description": "Read-only surface snapshot.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "park.request": {
        "name": "park.request",
        "description": (
            "Request commit of a held propose. Refused unless status is "
            "hold_unresolved and dependencies are now present. Does not "
            "bypass DPO."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["admit", "hold_unresolved", "reject", "outcome_unknown"],
                },
                "message_id": {"type": "string"},
            },
            "required": ["status", "message_id"],
        },
    },
    "oda.spawn": {
        "name": "oda.spawn",
        "description": "Cell v0 lock: spawning a bot is refused.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bot_name": {"type": "string"},
                "job": {"type": "string"},
            },
            "required": ["bot_name"],
        },
    },
    "oda.attach_skill": {
        "name": "oda.attach_skill",
        "description": "New rail = skill on an existing owner, not a new bot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "skill": {"type": "string"},
                "rail": {"type": "string"},
            },
            "required": ["owner", "skill", "rail"],
        },
    },
}


class ToolRegistry:
    def __init__(self, surface: GrokCellSurface) -> None:
        self.surface = surface
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "vault.query": self._vault_query,
            "bus.post": self._bus_post,
            "bus.drain": self._bus_drain,
            "surface.inspect": self._inspect,
            "park.request": self._park,
            "oda.spawn": self._spawn,
            "oda.attach_skill": self._attach,
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [TOOL_SCHEMAS[name] for name in sorted(TOOL_SCHEMAS)]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.handlers:
            raise KeyError(name)
        return self.handlers[name](arguments)

    def _vault_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.surface.vault.query(str(arguments["concept_id"]))

    def _bus_post(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ack = self.surface.post(
            Message(
                source_owner=str(arguments.get("source_owner") or MOUTH_OWNER),
                kind=str(arguments["kind"]),
                priority=int(arguments["priority"]),
                payload=dict(arguments.get("payload") or {}),
            )
        )
        return {"queued": ack.queued, "message_id": ack.message_id}

    def _bus_drain(self, arguments: dict[str, Any]) -> dict[str, Any]:
        items = self.surface.drain()
        return {"results": [item.to_json() for item in items]}

    def _inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.surface.inspect()

    def _park(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.surface.park_request(
            status=str(arguments["status"]),
            message_id=str(arguments["message_id"]),
        )

    def _spawn(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "decision": "refused",
            "reason": "oda_spawn_lock",
            "bot_name": arguments.get("bot_name"),
            "new_bot": False,
        }

    def _attach(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.surface.attach_skill(
            owner=str(arguments["owner"]),
            skill=str(arguments["skill"]),
            rail=str(arguments["rail"]),
        )


def mcp_manifest() -> dict[str, Any]:
    return {
        "schema_version": MCP_SCHEMA_VERSION,
        "tools": list(TOOL_SCHEMAS.values()),
        "notes": (
            "Tools are control-plane ports. They are not radio links, "
            "not occurrence types, and not a bot swarm."
        ),
    }
