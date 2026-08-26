"""Authoritative model identity and runtime resource contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .adaptive import AdaptiveParameter, AdaptiveRegistry
from .boundary import BoundaryState
from .canonical import stable_hash
from .errors import ValidationError
from .graph import Hypergraph
from .meta import RuleTemplate
from .pattern import Rule
from .schedulers import SchedulerKind


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    max_events: int = 10_000_000
    max_vertices: int = 1_000_000
    max_edges: int = 1_000_000
    max_incidences: int = 10_000_000
    max_matches_per_rule: int = 5_000_000
    max_total_activity: float = 1e300
    max_simulation_time: float = math.inf
    max_events_per_time_window: int = 100_000
    explosion_window: float = 1e-12
    invalid_hazard_policy: str = "raise"  # raise | disable_occurrence

    scheduler: SchedulerKind | str = SchedulerKind.DIRECT_SSA
    matcher_backend: str = "incremental"  # incremental | reference
    incremental_verify: bool = False

    thinning_window: float = 1.0
    max_thinning_windows_per_plan: int = 100_000

    def __post_init__(self) -> None:
        if self.invalid_hazard_policy not in {"raise", "disable_occurrence"}:
            raise ValueError("invalid_hazard_policy must be raise or disable_occurrence")
        if self.max_events <= 0:
            raise ValueError("max_events must be positive")
        if self.matcher_backend not in {"incremental", "reference"}:
            raise ValueError("matcher_backend must be incremental or reference")
        try:
            SchedulerKind(self.scheduler)
        except ValueError as exc:
            raise ValueError(f"Unknown scheduler {self.scheduler!r}") from exc
        if not math.isfinite(self.thinning_window) or self.thinning_window <= 0.0:
            raise ValueError("thinning_window must be finite and positive")
        if self.max_thinning_windows_per_plan <= 0:
            raise ValueError("max_thinning_windows_per_plan must be positive")

    @property
    def scheduler_kind(self) -> SchedulerKind:
        return SchedulerKind(self.scheduler)


@dataclass(slots=True)
class Model:
    graph: Hypergraph
    boundary: BoundaryState
    rules: tuple[Rule, ...]
    parameters: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    model_id: str = "model"
    version: str = "1.0.0"
    adaptive_parameters: tuple[AdaptiveParameter, ...] = ()
    rule_templates: tuple[RuleTemplate, ...] = ()
    hash: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValidationError("Duplicate rule IDs")
        template_ids = [template.template_id for template in self.rule_templates]
        if len(template_ids) != len(set(template_ids)):
            raise ValidationError("Duplicate rule template IDs")
        self.boundary.validate(set(self.graph.vertices))
        for handle in self.boundary.handles.values():
            if handle.binding is not None:
                vertex_type = self.graph.vertices[handle.binding].type_id
                if not self.graph.schema.is_vertex_compatible(vertex_type, handle.interface_type):
                    raise ValidationError(
                        f"Boundary {handle.handle_id!r} expects {handle.interface_type}, "
                        f"got {vertex_type}"
                    )
        AdaptiveRegistry(self.adaptive_parameters).validate(self.parameters)
        object.__setattr__(self, "hash", stable_hash(self.to_canonical()))

    def to_canonical(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "schema_hash": self.graph.schema.hash,
            "graph": self.graph.to_canonical(),
            "boundary": self.boundary.to_canonical(),
            "rules": [rule.hash for rule in sorted(self.rules, key=lambda item: item.rule_id)],
            "parameters": self.parameters,
            "memory": self.memory,
            "adaptive_parameters": self.adaptive_parameters,
            "rule_templates": [
                {
                    "template_id": template.template_id,
                    "version": template.version,
                    "prototype_hash": template.prototype.hash,
                    "parameters": template.parameters,
                    "max_instances": template.max_instances,
                }
                for template in sorted(self.rule_templates, key=lambda item: item.template_id)
            ],
        }
