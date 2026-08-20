"""Event records and runtime results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .boundary import BoundaryDelta, OutputEvent
from .graph import GraphDelta
from .rng import RandomDraw


class EventKind(str, Enum):
    INTERNAL_REWRITE = "internal_rewrite"
    EXTERNAL_INPUT = "external_input"
    SCHEDULED_ADAPTATION = "scheduled_adaptation"
    META_RULE_UPDATE = "meta_rule_update"


@dataclass(slots=True)
class EventRecord:
    event_id: str
    event_index: int
    kind: EventKind
    pre_time: float
    post_time: float
    delta_time: float
    cause: dict[str, Any]
    random_draws: list[RandomDraw]
    graph_delta: GraphDelta
    boundary_delta: BoundaryDelta
    parameter_before: dict[str, Any]
    parameter_after: dict[str, Any]
    memory_before: dict[str, Any]
    memory_after: dict[str, Any]
    pre_state_hash: str
    post_state_hash: str
    outputs: list[OutputEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StepStatus(str, Enum):
    FIRED = "fired"
    PROCESSED_EXTERNAL = "processed_external"
    ABSORBED = "absorbed"
    PAUSED = "paused"


@dataclass(slots=True)
class StepResult:
    status: StepStatus
    event: EventRecord | None = None
    reason: str | None = None
