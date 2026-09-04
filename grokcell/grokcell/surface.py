"""Stateful GrokCell surface. One mouth. Chat is not the database."""
from __future__ import annotations

from dataclasses import dataclass, field

from .bus import as_item, classify, drain_order
from .construction import build_runtime, graph_component_names, licensed_assemble
from .messages import DrainItem, Message, PostAck
from .protocol import MOUTH_OWNER, SURFACE_VERSION
from .vault import ConstraintVault


@dataclass
class GrokCellSurface:
    vault: ConstraintVault
    runtime: object
    queued: list[Message] = field(default_factory=list)
    held: dict[str, Message] = field(default_factory=dict)
    seq: int = 0
    inject_seq: int = 0

    @classmethod
    def open(cls, vault: ConstraintVault | None = None) -> "GrokCellSurface":
        loaded = vault if vault is not None else ConstraintVault.load()
        return cls(vault=loaded, runtime=build_runtime())

    def post(self, message: Message) -> PostAck:
        self.seq += 1
        identified = message.with_identity(f"m-{self.seq:04d}", self.seq)
        self.queued.append(identified)
        return PostAck(queued=True, message_id=identified.message_id)

    def components(self) -> list[str]:
        return graph_component_names(self.runtime)

    def drain(self) -> list[DrainItem]:
        batch = drain_order(self.queued)
        self.queued = []
        results: list[DrainItem] = []
        for message in batch:
            results.append(self._dispatch(message))
        return results

    def _dispatch(self, message: Message) -> DrainItem:
        status, reason = classify(
            message,
            components=self.components(),
            vault=self.vault,
        )
        if status == "admit":
            self._commit_propose(message)
            return as_item(message, status, reason)
        if status == "hold_unresolved":
            self.held[message.message_id] = message
            return as_item(message, status, reason)
        self.vault.record_note(
            status=status,
            reason=reason,
            message_id=message.message_id,
        )
        return as_item(message, status, reason)

    def _commit_propose(self, message: Message) -> None:
        payload = message.payload
        self.inject_seq += 1
        licensed_assemble(
            self.runtime,
            name=str(payload["name"]),
            constraint=str(payload.get("constraint") or ""),
            seq=self.inject_seq,
        )

    def park_request(self, *, status: str, message_id: str) -> dict:
        if status != "hold_unresolved":
            return {
                "decision": "refused",
                "reason": f"claim status {status!r} does not license park",
                "message_id": message_id,
                "bypasses_dpo": False,
            }
        message = self.held.get(message_id)
        if message is None:
            return {
                "decision": "refused",
                "reason": "message is not currently held",
                "message_id": message_id,
                "bypasses_dpo": False,
            }
        next_status, reason = classify(
            message,
            components=self.components(),
            vault=self.vault,
        )
        if next_status != "admit":
            detail = "dependency" if reason == "missing_dependency" else reason
            return {
                "decision": "refused",
                "reason": detail,
                "message_id": message_id,
                "bypasses_dpo": False,
            }
        self._commit_propose(message)
        del self.held[message_id]
        return {
            "decision": "accepted",
            "reason": "hold resolved; kernel validated assemble-component",
            "message_id": message_id,
            "bypasses_dpo": False,
        }

    def attach_skill(self, *, owner: str, skill: str, rail: str) -> dict:
        if owner != MOUTH_OWNER:
            return {
                "decision": "refused",
                "reason": "v0 attaches skills only on MOUTH",
                "new_bot": False,
            }
        skills = list(self.runtime.memory.get("skills_on_mouth", []))
        token = skill if not rail else f"{skill}:{rail}"
        if token not in skills:
            skills.append(skill)
        self.runtime.memory["skills_on_mouth"] = skills
        return {
            "decision": "accepted",
            "reason": f"skill rail {rail} on {owner}",
            "new_bot": False,
        }

    def inspect(self) -> dict:
        rule_ids = sorted(self.runtime.rules)
        held = [
            {
                "message_id": item.message_id,
                "kind": item.kind,
                "priority": item.priority,
                "payload": dict(item.payload),
            }
            for item in self.held.values()
        ]
        return {
            "surface_version": SURFACE_VERSION,
            "owners": list(self.runtime.memory.get("owners", [MOUTH_OWNER])),
            "bots_spawned": int(self.runtime.memory.get("bots_spawned", 0)),
            "skills_on_mouth": list(self.runtime.memory.get("skills_on_mouth", [])),
            "components": self.components(),
            "state_hash": self.runtime.state_hash,
            "event_index": int(self.runtime.event_index),
            "time": float(self.runtime.time),
            "rule_ids": rule_ids,
            "hold_queue": len(self.held),
            "queued": len(self.queued),
            "held": held,
        }
