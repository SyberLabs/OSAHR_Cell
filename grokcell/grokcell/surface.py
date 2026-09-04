"""Stateful GrokCell surface. Chat is not the database. Park licenses G."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .bus import as_item, classify, drain_order
from .construction import (
    build_runtime,
    graph_component_names,
    licensed_assemble,
    runtime_from_snapshot,
)
from .fidelity import FidelityStore
from .messages import DrainItem, Message, PostAck
from .protocol import MOUTH_OWNER, SURFACE_VERSION
from .snapshot import SnapshotStore, SurfaceSnapshot
from .vault import ConstraintVault


@dataclass
class GrokCellSurface:
    vault: ConstraintVault
    runtime: object
    fidelity: FidelityStore
    snapshots: SnapshotStore
    queued: list[Message] = field(default_factory=list)
    held: dict[str, Message] = field(default_factory=dict)
    seq: int = 0
    inject_seq: int = 0

    @classmethod
    def open(
        cls,
        vault: ConstraintVault | None = None,
        fidelity: FidelityStore | None = None,
        state: Path | None = None,
    ) -> "GrokCellSurface":
        loaded = vault if vault is not None else ConstraintVault.load()
        scores = fidelity if fidelity is not None else FidelityStore.load()
        store = SnapshotStore.load(state)
        pair = store.load_pair()
        if pair is None:
            return cls(
                vault=loaded,
                runtime=build_runtime(),
                fidelity=scores,
                snapshots=store,
            )
        kernel, surface = pair
        return cls(
            vault=loaded,
            runtime=runtime_from_snapshot(kernel),
            fidelity=scores,
            snapshots=store,
            queued=list(surface.queued),
            held=dict(surface.held),
            seq=surface.seq,
            inject_seq=surface.inject_seq,
        )

    def _persist(self) -> None:
        self.snapshots.save(
            self.runtime,
            SurfaceSnapshot(
                seq=self.seq,
                inject_seq=self.inject_seq,
                queued=list(self.queued),
                held=dict(self.held),
            ),
        )

    def post(self, message: Message) -> PostAck:
        self.seq += 1
        identified = message.with_identity(f"m-{self.seq:04d}", self.seq)
        self.queued.append(identified)
        self._persist()
        return PostAck(queued=True, message_id=identified.message_id)

    def components(self) -> list[str]:
        return graph_component_names(self.runtime)

    def drain(self) -> list[DrainItem]:
        batch = drain_order(self.queued)
        self.queued = []
        results: list[DrainItem] = []
        for message in batch:
            results.append(self._dispatch(message))
        self._persist()
        return results

    def owners(self) -> list[str]:
        return list(self.runtime.memory.get("owners", [MOUTH_OWNER]))

    def _dispatch(self, message: Message) -> DrainItem:
        status, reason = classify(
            message,
            components=self.components(),
            owners=self.owners(),
            vault=self.vault,
            fidelity=self.fidelity,
        )
        if status == "admit":
            if message.kind == "oda.spawn":
                self._commit_spawn(message)
            else:
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

    def _commit_spawn(self, message: Message) -> None:
        self.spawn_owner(
            bot_name=str(message.payload.get("bot_name") or ""),
            job=str(message.payload.get("job") or ""),
        )

    def spawn_owner(self, *, bot_name: str, job: str = "") -> dict:
        name = str(bot_name or "").strip()
        if not name:
            return {
                "decision": "refused",
                "reason": "missing_name",
                "bot_name": bot_name,
                "new_bot": False,
            }
        owners = self.owners()
        if name in owners:
            return {
                "decision": "refused",
                "reason": "duplicate_owner",
                "bot_name": name,
                "new_bot": False,
            }
        owners.append(name)
        self.runtime.memory["owners"] = owners
        self.runtime.memory["bots_spawned"] = int(
            self.runtime.memory.get("bots_spawned", 0)
        ) + 1
        skills = dict(self.runtime.memory.get("skills") or {})
        skills.setdefault(name, [])
        self.runtime.memory["skills"] = skills
        self._persist()
        return {
            "decision": "accepted",
            "reason": "owner_registered",
            "bot_name": name,
            "job": job,
            "new_bot": True,
        }

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
            owners=self.owners(),
            vault=self.vault,
            fidelity=self.fidelity,
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
        self._persist()
        return {
            "decision": "accepted",
            "reason": "hold resolved; kernel validated assemble-component",
            "message_id": message_id,
            "bypasses_dpo": False,
        }

    def attach_skill(self, *, owner: str, skill: str, rail: str) -> dict:
        if owner not in self.owners():
            return {
                "decision": "refused",
                "reason": "unknown_owner",
                "new_bot": False,
            }
        skills = dict(self.runtime.memory.get("skills") or {})
        bucket = list(skills.get(owner, []))
        if skill not in bucket:
            bucket.append(skill)
        skills[owner] = bucket
        self.runtime.memory["skills"] = skills
        self._persist()
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
            "owners": self.owners(),
            "bots_spawned": int(self.runtime.memory.get("bots_spawned", 0)),
            "skills": {
                key: list(value)
                for key, value in dict(self.runtime.memory.get("skills") or {}).items()
            },
            "components": self.components(),
            "state_hash": self.runtime.state_hash,
            "event_index": int(self.runtime.event_index),
            "time": float(self.runtime.time),
            "rule_ids": rule_ids,
            "hold_queue": len(self.held),
            "queued": len(self.queued),
            "held": held,
        }
