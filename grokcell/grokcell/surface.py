"""Stateful GrokCell surface. Chat is not the database. Park licenses G."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar

from osahr import RuntimeConfig

from .artifact import Artifact, ArtifactStore
from .bus import as_item, classify, drain_order
from .construction import (
    build_runtime,
    construction_model,
    graph_component_names,
    licensed_assemble,
    runtime_from_snapshot,
)
from .fidelity import FidelityStore
from .messages import DrainItem, Message, PostAck, validate_owner_name
from .protocol import MOUTH_OWNER, SURFACE_VERSION
from .snapshot import SnapshotStore, SurfaceSnapshot
from .vault import ConstraintVault

Result = TypeVar("Result")


@dataclass
class GrokCellSurface:
    vault: ConstraintVault
    runtime: object
    fidelity: FidelityStore
    snapshots: SnapshotStore
    artifacts: ArtifactStore
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
        artifacts = ArtifactStore(store.root / "artifacts")
        with store.locked():
            pair = store.load_pair(
                legacy_model=construction_model(),
                legacy_config=RuntimeConfig(),
            )
            if pair is None:
                surface = cls(
                    vault=loaded,
                    runtime=build_runtime(),
                    fidelity=scores,
                    snapshots=store,
                    artifacts=artifacts,
                )
            else:
                kernel, saved = pair
                surface = cls(
                    vault=loaded,
                    runtime=runtime_from_snapshot(kernel),
                    fidelity=scores,
                    snapshots=store,
                    artifacts=artifacts,
                    queued=list(saved.queued),
                    held=dict(saved.held),
                    seq=saved.seq,
                    inject_seq=saved.inject_seq,
                )
            surface.artifacts.prune_except(set(surface.components()))
        return surface

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

    def _transaction(self, operation: Callable[[], Result]) -> Result:
        with self.snapshots.locked():
            before = (
                copy.deepcopy(self.runtime),
                copy.deepcopy(self.queued),
                copy.deepcopy(self.held),
                self.seq,
                self.inject_seq,
                self.artifacts.names(),
            )
            try:
                result = operation()
                self._persist()
                return result
            except BaseException:
                runtime, queued, held, seq, inject_seq, artifact_names = before
                self.runtime = runtime
                self.queued = queued
                self.held = held
                self.seq = seq
                self.inject_seq = inject_seq
                try:
                    self.artifacts.prune_except(artifact_names)
                except OSError:
                    pass
                raise

    def post(self, message: Message) -> PostAck:
        def commit() -> PostAck:
            owner = str(message.source_owner or "").strip()
            if owner not in self.owners():
                return PostAck(queued=False, message_id="", reason="unknown_owner")
            self.seq += 1
            identified = message.with_identity(f"m-{self.seq:04d}", self.seq)
            self.queued.append(identified)
            return PostAck(queued=True, message_id=identified.message_id)

        return self._transaction(commit)

    def components(self) -> list[str]:
        return graph_component_names(self.runtime)

    def drain(self) -> list[DrainItem]:
        with self.snapshots.locked():
            results: list[DrainItem] = []
            for message in drain_order(list(self.queued)):
                def commit(message: Message = message) -> DrainItem:
                    result = self._dispatch(message)
                    self.queued.remove(message)
                    return result

                results.append(self._transaction(commit))
            return results

    def owners(self) -> list[str]:
        return list(self.runtime.memory.get("owners", [MOUTH_OWNER]))

    def _dispatch(self, message: Message) -> DrainItem:
        status, reason, artifact = classify(
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
                if artifact is None:
                    raise RuntimeError("admitted proposal has no validated artifact")
                self._commit_propose(message, artifact)
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

    def _commit_propose(self, message: Message, artifact: Artifact) -> None:
        payload = message.payload
        candidate = copy.deepcopy(self.runtime)
        next_inject_seq = self.inject_seq + 1
        licensed_assemble(
            candidate,
            name=str(payload["name"]),
            constraint=str(payload.get("constraint") or ""),
            seq=next_inject_seq,
        )
        self.artifacts.materialize(artifact)
        self.runtime = candidate
        self.inject_seq = next_inject_seq

    def _commit_spawn(self, message: Message) -> None:
        self._register_owner(
            bot_name=str(message.payload.get("bot_name") or ""),
        )

    def _register_owner(self, *, bot_name: str) -> None:
        owners = self.owners()
        owners.append(bot_name)
        self.runtime.memory["owners"] = owners
        self.runtime.memory["bots_spawned"] = int(
            self.runtime.memory.get("bots_spawned", 0)
        ) + 1
        skills = dict(self.runtime.memory.get("skills") or {})
        skills.setdefault(bot_name, [])
        self.runtime.memory["skills"] = skills

    def spawn_owner(self, *, bot_name: str, job: str = "") -> dict:
        try:
            name = validate_owner_name(bot_name)
        except ValueError:
            return {
                "decision": "refused",
                "reason": "invalid_owner_name",
                "bot_name": bot_name,
                "new_bot": False,
            }
        def commit() -> dict:
            if name in self.owners():
                return {
                    "decision": "refused",
                    "reason": "duplicate_owner",
                    "bot_name": name,
                    "new_bot": False,
                }
            self._register_owner(bot_name=name)
            return {
                "decision": "accepted",
                "reason": "owner_registered",
                "bot_name": name,
                "job": job,
                "new_bot": True,
            }

        return self._transaction(commit)

    def park_request(
        self,
        *,
        status: str = "",
        message_id: str = "",
        act: str = "",
        name: str = "",
    ) -> dict:
        verb = str(act or "").strip()
        if verb:
            with self.snapshots.locked():
                if name not in self.components() and name in self.artifacts.names():
                    return {
                        "decision": "refused",
                        "reason": "component_not_admitted",
                        "name": name,
                        "bypasses_dpo": False,
                    }
                return self.artifacts.act(act=verb, name=name)
        if status != "hold_unresolved":
            return {
                "decision": "refused",
                "reason": f"claim status {status!r} does not license park",
                "message_id": message_id,
                "bypasses_dpo": False,
            }
        def commit() -> dict:
            message = self.held.get(message_id)
            if message is None:
                return {
                    "decision": "refused",
                    "reason": "message is not currently held",
                    "message_id": message_id,
                    "bypasses_dpo": False,
                }
            next_status, reason, artifact = classify(
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
            if artifact is None:
                raise RuntimeError("admitted held proposal has no validated artifact")
            self._commit_propose(message, artifact)
            del self.held[message_id]
            return {
                "decision": "accepted",
                "reason": "hold resolved; kernel validated assemble-component",
                "message_id": message_id,
                "bypasses_dpo": False,
            }

        return self._transaction(commit)

    def attach_skill(self, *, owner: str, skill: str, rail: str) -> dict:
        def commit() -> dict:
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
            return {
                "decision": "accepted",
                "reason": f"skill rail {rail} on {owner}",
                "new_bot": False,
            }

        return self._transaction(commit)

    def inspect(self) -> dict:
        with self.snapshots.locked():
            rule_ids = sorted(self.runtime.rules)
            held = [
                {
                    "message_id": item.message_id,
                    "kind": item.kind,
                    "priority": item.priority,
                    "payload": copy.deepcopy(item.payload),
                }
                for item in self.held.values()
            ]
            components = self.components()
            artifacts = [
                item
                for item in self.artifacts.list()
                if item["name"] in set(components)
            ]
            return {
                "surface_version": SURFACE_VERSION,
                "owners": self.owners(),
                "bots_spawned": int(self.runtime.memory.get("bots_spawned", 0)),
                "skills": {
                    key: list(value)
                    for key, value in dict(
                        self.runtime.memory.get("skills") or {}
                    ).items()
                },
                "components": components,
                "state_hash": self.runtime.state_hash,
                "event_index": int(self.runtime.event_index),
                "time": float(self.runtime.time),
                "rule_ids": rule_ids,
                "hold_queue": len(self.held),
                "queued": len(self.queued),
                "held": held,
                "artifacts": artifacts,
            }
