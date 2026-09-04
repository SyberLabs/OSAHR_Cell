"""Control-plane messages. Not OSAHR occurrence types."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, replace
from typing import Any


_COMPONENT_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_OWNER_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def validate_component_name(value: object) -> str:
    """Return an exact storage-safe component name or fail closed."""
    if (
        not isinstance(value, str)
        or not _COMPONENT_NAME.fullmatch(value)
        or value.split(".", 1)[0] in _WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("invalid_component_name")
    return value


def validate_owner_name(value: object) -> str:
    """Return an exact owner identifier or fail closed."""
    if not isinstance(value, str) or not _OWNER_NAME.fullmatch(value):
        raise ValueError("invalid_owner_name")
    return value


def validate_message_payload(kind: str, payload: dict[str, Any]) -> None:
    if kind == "forge.propose":
        validate_component_name(payload.get("name"))
        constraint = payload.get("constraint")
        if not isinstance(constraint, str) or not constraint:
            raise ValueError("invalid_constraint")
        dependencies = payload.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise ValueError("invalid_dependencies")
        for dependency in dependencies:
            validate_component_name(dependency)
        module = payload.get("module")
        tests = payload.get("tests")
        if (module is None) != (tests is None):
            raise ValueError("incomplete_artifact")
        if module is not None and (
            not isinstance(module, str)
            or not module.strip()
            or not isinstance(tests, str)
            or not tests.strip()
        ):
            raise ValueError("invalid_artifact")
    elif kind == "oda.spawn":
        validate_owner_name(payload.get("bot_name"))


@dataclass(frozen=True, slots=True)
class Message:
    source_owner: str
    kind: str
    priority: int
    payload: dict[str, Any]
    message_id: str = ""
    seq: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a dictionary")
        validate_message_payload(self.kind, self.payload)
        object.__setattr__(self, "payload", copy.deepcopy(self.payload))

    def with_identity(self, message_id: str, seq: int) -> "Message":
        return replace(
            self,
            message_id=message_id,
            seq=int(seq),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "source_owner": self.source_owner,
            "kind": self.kind,
            "priority": self.priority,
            "payload": copy.deepcopy(self.payload),
            "message_id": self.message_id,
            "seq": self.seq,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "Message":
        return cls(
            source_owner=str(payload["source_owner"]),
            kind=str(payload["kind"]),
            priority=int(payload["priority"]),
            payload=copy.deepcopy(payload.get("payload") or {}),
            message_id=str(payload.get("message_id") or ""),
            seq=int(payload.get("seq") or 0),
        )


@dataclass(frozen=True, slots=True)
class PostAck:
    queued: bool
    message_id: str
    reason: str = ""


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
