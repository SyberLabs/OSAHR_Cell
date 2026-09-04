"""Serializable runtime state records kept separate from event-loop orchestration."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any

from .boundary import BoundaryState, ExternalEvent, OutputEvent
from .canonical import stable_hash
from .errors import ValidationError
from .graph import Hypergraph
from .matcher import Match
from .meta import MetaRuleEvent
from .model import RuntimeConfig
from .pattern import Rule, StateAssignment
from .rng import RandomDraw
from .schedulers import NextReactionSnapshot, SchedulerKind, ThinningAudit


@dataclass(frozen=True, slots=True, order=True)
class ScheduledAdaptation:
    simulation_time: float
    source_sequence: int
    update_id: str
    assignments: tuple[StateAssignment, ...] = field(compare=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.simulation_time, bool)
            or not isinstance(self.simulation_time, (int, float))
            or not math.isfinite(self.simulation_time)
            or self.simulation_time < 0.0
        ):
            raise ValidationError("Scheduled adaptation time must be finite and non-negative")
        if (
            isinstance(self.source_sequence, bool)
            or not isinstance(self.source_sequence, int)
            or self.source_sequence < 0
        ):
            raise ValidationError("Scheduled adaptation source sequence must be non-negative")
        if not isinstance(self.update_id, str) or not self.update_id:
            raise ValidationError("Scheduled adaptation ID cannot be empty")
        if not all(isinstance(item, StateAssignment) for item in self.assignments):
            raise ValidationError("Scheduled adaptation assignments are invalid")
        object.__setattr__(self, "assignments", copy.deepcopy(tuple(self.assignments)))


@dataclass(frozen=True, slots=True)
class EnabledOccurrence:
    rule: Rule
    match: Match
    hazard: float


@dataclass(slots=True)
class PendingInternalEvent:
    absolute_time: float
    occurrence: EnabledOccurrence
    draws: list[RandomDraw]
    planned_at_time: float
    planned_state_hash: str
    total_activity: float
    scheduler_kind: SchedulerKind = SchedulerKind.DIRECT_SSA
    survival_integral_exact: bool = True
    survival_integral: float | None = None
    integrity_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.occurrence = copy.deepcopy(self.occurrence)
        self.draws = copy.deepcopy(list(self.draws))
        self.integrity_hash = self.calculate_integrity_hash()

    def calculate_integrity_hash(self) -> str:
        return stable_hash(
            {
                "absolute_time": self.absolute_time,
                "rule_id": self.occurrence.rule.rule_id,
                "rule_hash": self.occurrence.rule.hash,
                "match": {
                    "rule_id": self.occurrence.match.rule_id,
                    "vertex_map": self.occurrence.match.vertex_map,
                    "edge_map": self.occurrence.match.edge_map,
                    "bindings": self.occurrence.match.bindings,
                    "graph_epoch": self.occurrence.match.graph_epoch,
                    "match_id": self.occurrence.match.match_id,
                },
                "hazard": self.occurrence.hazard,
                "draws": self.draws,
                "planned_at_time": self.planned_at_time,
                "planned_state_hash": self.planned_state_hash,
                "total_activity": self.total_activity,
                "scheduler_kind": self.scheduler_kind.value,
                "survival_integral_exact": self.survival_integral_exact,
                "survival_integral": self.survival_integral,
            }
        )

@dataclass(slots=True)
class RuntimeSnapshot:
    model_hash: str
    config: RuntimeConfig
    graph: Hypergraph
    boundary: BoundaryState
    rules: dict[str, Rule]
    parameters: dict[str, Any]
    memory: dict[str, Any]
    time: float
    last_event_time: float
    event_index: int
    root_seed: int
    rng_states: dict[str, tuple[int, int, int, int]]
    recent_event_times: tuple[float, ...]
    external_queue: list[ExternalEvent]
    adaptation_queue: list[ScheduledAdaptation]
    meta_queue: list[MetaRuleEvent]
    pending_internal: PendingInternalEvent | None
    output_events: list[OutputEvent]
    run_id: str
    scheduler_kind: SchedulerKind
    next_reaction_snapshot: NextReactionSnapshot | None = None
    next_reaction_initialized: bool = False
    thinning_audit: ThinningAudit = field(default_factory=ThinningAudit)
    continuation_allowed: bool = True
    format_version: int = 2
    identity_version: int = 2
    integrity_hash: str = ""

    def calculate_integrity_hash(self) -> str:
        next_reaction = None
        if self.next_reaction_snapshot is not None:
            next_reaction = {
                "channels": [
                    {
                        "key": (key.rule_id, key.match_id),
                        "hazard": channel.hazard,
                        "internal_time": channel.internal_time,
                        "threshold": channel.threshold,
                        "last_update_time": channel.last_update_time,
                        "planned_time": (
                            "infinity"
                            if math.isinf(channel.planned_time)
                            else channel.planned_time
                        ),
                        "version": channel.version,
                    }
                    for key, channel in sorted(
                        self.next_reaction_snapshot.channels.items(),
                        key=lambda item: (item[0].rule_id, item[0].match_id),
                    )
                ],
                "audit_draws": self.next_reaction_snapshot.audit_draws,
            }
        return stable_hash(
            {
                "model_hash": self.model_hash,
                "config": self.config.to_canonical(),
                "graph": self.graph.to_canonical(),
                "boundary": self.boundary.to_canonical(),
                "rules": {
                    rule_id: rule.to_canonical()
                    for rule_id, rule in sorted(self.rules.items())
                },
                "parameters": self.parameters,
                "memory": self.memory,
                "time": self.time,
                "last_event_time": self.last_event_time,
                "event_index": self.event_index,
                "root_seed": self.root_seed,
                "rng_states": self.rng_states,
                "recent_event_times": self.recent_event_times,
                "external_queue": self.external_queue,
                "adaptation_queue": self.adaptation_queue,
                "meta_queue": self.meta_queue,
                "pending_internal": (
                    None
                    if self.pending_internal is None
                    else self.pending_internal.calculate_integrity_hash()
                ),
                "output_events": self.output_events,
                "run_id": self.run_id,
                "scheduler_kind": self.scheduler_kind.value,
                "next_reaction": next_reaction,
                "next_reaction_initialized": self.next_reaction_initialized,
                "thinning_audit": self.thinning_audit,
                "continuation_allowed": self.continuation_allowed,
                "format_version": self.format_version,
                "identity_version": self.identity_version,
            }
        )

    def seal(self) -> "RuntimeSnapshot":
        self.integrity_hash = self.calculate_integrity_hash()
        return self


@dataclass(slots=True)
class StepCheckpoint:
    graph: Hypergraph
    boundary: BoundaryState
    rules: dict[str, Rule]
    parameters: dict[str, Any]
    memory: dict[str, Any]
    time: float
    last_event_time: float
    event_index: int
    rng_states: dict[str, tuple[int, int, int, int]]
    external_queue: list[ExternalEvent]
    adaptation_queue: list[ScheduledAdaptation]
    meta_queue: list[MetaRuleEvent]
    pending_internal: PendingInternalEvent | None
    pending_integrity: str | None
    next_reaction_snapshot: NextReactionSnapshot | None
    next_reaction_initialized: bool
    thinning_audit: ThinningAudit
    event_log_length: int
    output_events_length: int
    recent_event_times: tuple[float, ...]


@dataclass(slots=True)
class PlanCheckpoint:
    rng_states: dict[str, tuple[int, int, int, int]]
    pending_internal: PendingInternalEvent | None
    pending_integrity: str | None
    next_reaction_snapshot: NextReactionSnapshot | None
    next_reaction_initialized: bool
    thinning_audit: ThinningAudit
