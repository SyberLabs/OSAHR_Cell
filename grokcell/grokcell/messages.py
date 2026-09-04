"""Control-plane messages. Not OSAHR occurrence types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Message:
    source_owner: str
    kind: str
    priority: int
    payload: dict[str, Any]
    message_id: str = ""
    seq: int = 0

    def with_identity(self, message_id: str, seq: int) -> "Message":
        return Message(
            source_owner=self.source_owner,
            kind=self.kind,
            priority=int(self.priority),
            payload=dict(self.payload),
            message_id=message_id,
            seq=int(seq),
        )


@dataclass(frozen=True, slots=True)
class PostAck:
    queued: bool
    message_id: str


@dataclass(frozen=True, slots=True)
class DrainItem:
    message_id: str
    kind: str
    status: str
    reason: str
    priority: int

    def to_json(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "kind": self.kind,
            "status": self.status,
            "reason": self.reason,
            "priority": self.priority,
        }
