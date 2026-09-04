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
        "description": (
            "Queue a typed control-plane message. source_owner must be "
            "the bound registered owner. Does not rewrite G."
        ),
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
            "License a held propose onto G, or send/publish/delete/sign "
            "admitted artifact files. Does not bypass DPO."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["admit", "hold_unresolved", "reject", "outcome_unknown"],
                },
                "message_id": {"type": "string"},
                "act": {
                    "type": "string",
                    "enum": ["send", "publish", "delete", "sign"],
                },
                "name": {"type": "string"},
            },
        },
    },
    "oda.spawn": {
        "name": "oda.spawn",
        "description": (
            "Register a grokbot owner on the surface. Does not rewrite G. "
            "Park still licenses construction."
        ),
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
        "description": "Attach a skill rail to an existing owner.",
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
    def __init__(
        self,
        surface: GrokCellSurface,
        bound_owner: str | None = MOUTH_OWNER,
    ) -> None:
        self.surface = surface
        if bound_owner is None:
            self.bound_owner: str | None = None
        else:
            name = str(bound_owner).strip()
            self.bound_owner = name or None
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "vault.query": self._vault_query,
            "bus.post": self._bus_post,
            "bus.drain": self._bus_drain,
            "surface.inspect": self._inspect,
            "park.request": self._park,
            "oda.spawn": self._spawn,
            "oda.attach_skill": self._attach,
        }

    def bind(self, owner: str) -> dict[str, Any]:
        name = str(owner or "").strip()
        if not name or name not in self.surface.owners():
            return {
                "decision": "refused",
                "reason": "unknown_owner",
                "owner": name,
            }
        self.bound_owner = name
        return {
            "decision": "accepted",
            "reason": "session_bound",
            "owner": name,
        }

    def _session_reason(self, source_owner: str) -> str | None:
        if self.bound_owner is None:
            return "unbound_session"
        owner = str(source_owner or "").strip()
        if owner not in self.surface.owners():
            return "unknown_owner"
        if owner != self.bound_owner:
            return "session_mismatch"
        return None

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
        owner = str(arguments.get("source_owner") or "").strip()
        reason = self._session_reason(owner)
        if reason is not None:
            return {"queued": False, "message_id": "", "reason": reason}
        ack = self.surface.post(
            Message(
                source_owner=owner,
                kind=str(arguments["kind"]),
                priority=int(arguments["priority"]),
                payload=dict(arguments.get("payload") or {}),
            )
        )
        return {
            "queued": ack.queued,
            "message_id": ack.message_id,
            "reason": ack.reason,
        }

    def _bus_drain(self, arguments: dict[str, Any]) -> dict[str, Any]:
        items = self.surface.drain()
        return {"results": [item.to_json() for item in items]}

    def _inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.surface.inspect()

    def _park(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.surface.park_request(
            status=str(arguments.get("status") or ""),
            message_id=str(arguments.get("message_id") or ""),
            act=str(arguments.get("act") or ""),
            name=str(arguments.get("name") or ""),
        )

    def _spawn(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.bound_owner is None:
            return {
                "decision": "refused",
                "reason": "unbound_session",
                "bot_name": str(arguments.get("bot_name") or ""),
                "new_bot": False,
            }
        return self.surface.spawn_owner(
            bot_name=str(arguments.get("bot_name") or ""),
            job=str(arguments.get("job") or ""),
        )

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
            "not occurrence types. Spawn registers owners; it does not rewrite G."
        ),
    }
