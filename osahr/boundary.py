"""Typed open-system boundaries and external events."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .canonical import validate_state_value
from .errors import ValidationError
from .ids import EntityId
from .schema import AttributeSpec


class BoundaryDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"


class InputMode(str, Enum):
    MERGE_BOUND_VERTEX_ATTRIBUTES = "merge_bound_vertex_attributes"
    REPLACE_BOUND_VERTEX_ATTRIBUTES = "replace_bound_vertex_attributes"
    SIGNAL_ONLY = "signal_only"


@dataclass(slots=True)
class BoundaryHandle:
    handle_id: str
    direction: BoundaryDirection
    interface_type: str
    binding: EntityId | None = None
    nullable: bool = False
    payload_schema: dict[str, AttributeSpec] = field(default_factory=dict)
    allow_payload_extensions: bool = False
    input_mode: InputMode = InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate_payload(self, payload: dict[str, Any]) -> None:
        try:
            validate_state_value(payload)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Boundary payload is not finite canonical data") from exc
        if not self.allow_payload_extensions:
            unknown = set(payload) - self.payload_schema.keys()
            if unknown and self.payload_schema:
                raise ValidationError(
                    f"Unknown payload fields for {self.handle_id}: {sorted(unknown)!r}"
                )
        for name, spec in self.payload_schema.items():
            if spec.required and name not in payload:
                raise ValidationError(f"Missing required payload field {name!r}")
            if name in payload:
                spec.validate(name, payload[name])


@dataclass(slots=True)
class BoundaryState:
    handles: dict[str, BoundaryHandle] = field(default_factory=dict)

    def clone(self) -> "BoundaryState":
        return copy.deepcopy(self)

    def add(self, handle: BoundaryHandle) -> None:
        if handle.handle_id in self.handles:
            raise ValidationError(f"Duplicate boundary handle {handle.handle_id!r}")
        self.handles[handle.handle_id] = handle

    def validate(self, graph_vertex_ids: set[EntityId]) -> None:
        for handle in self.handles.values():
            if handle.binding is None:
                if not handle.nullable:
                    raise ValidationError(f"Boundary handle {handle.handle_id!r} is unbound")
            elif handle.binding not in graph_vertex_ids:
                raise ValidationError(
                    f"Boundary handle {handle.handle_id!r} binds missing vertex {handle.binding}"
                )

    def to_canonical(self) -> dict[str, Any]:
        return {
            handle_id: {
                "direction": handle.direction.value,
                "interface_type": handle.interface_type,
                "binding": None if handle.binding is None else str(handle.binding),
                "nullable": handle.nullable,
                "payload_schema": handle.payload_schema,
                "allow_payload_extensions": handle.allow_payload_extensions,
                "input_mode": handle.input_mode.value,
                "metadata": handle.metadata,
            }
            for handle_id, handle in sorted(self.handles.items())
        }


@dataclass(frozen=True, slots=True, order=True)
class ExternalEvent:
    simulation_time: float
    source_namespace: str
    source_sequence: int
    event_id: str
    handle_id: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        if (
            isinstance(self.simulation_time, bool)
            or not isinstance(self.simulation_time, (int, float))
            or not math.isfinite(self.simulation_time)
            or self.simulation_time < 0.0
        ):
            raise ValidationError("External event time must be finite and non-negative")
        if not isinstance(self.source_namespace, str) or not self.source_namespace:
            raise ValidationError("External event source namespace cannot be empty")
        if (
            isinstance(self.source_sequence, bool)
            or not isinstance(self.source_sequence, int)
            or self.source_sequence < 0
        ):
            raise ValidationError("External event source sequence must be non-negative")
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValidationError("External event ID cannot be empty")
        if not isinstance(self.handle_id, str) or not self.handle_id:
            raise ValidationError("External event handle ID cannot be empty")
        if not isinstance(self.payload, Mapping):
            raise ValidationError("External event payload must be a mapping")
        object.__setattr__(self, "payload", copy.deepcopy(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class OutputEvent:
    event_id: str
    simulation_time: float
    event_index: int
    source_handle: str
    event_type: str
    payload: dict[str, Any]
    causing_event_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.event_id, str)
            or not self.event_id
            or isinstance(self.simulation_time, bool)
            or not isinstance(self.simulation_time, (int, float))
            or not math.isfinite(self.simulation_time)
            or self.simulation_time < 0.0
            or isinstance(self.event_index, bool)
            or not isinstance(self.event_index, int)
            or self.event_index < 0
            or not isinstance(self.source_handle, str)
            or not self.source_handle
            or not isinstance(self.event_type, str)
            or not self.event_type
            or not isinstance(self.causing_event_id, str)
            or not self.causing_event_id
        ):
            raise ValidationError("Output event identity is invalid")
        if not isinstance(self.payload, Mapping):
            raise ValidationError("Output event payload must be a mapping")
        object.__setattr__(self, "payload", copy.deepcopy(dict(self.payload)))


@dataclass(slots=True)
class BoundaryDelta:
    before: dict[str, EntityId | None] = field(default_factory=dict)
    after: dict[str, EntityId | None] = field(default_factory=dict)
    deleted_handles: dict[str, BoundaryHandle] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.before or self.after or self.deleted_handles)
